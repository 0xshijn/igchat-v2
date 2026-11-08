package bridge

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"

	"github.com/rs/zerolog"
	"go.mau.fi/util/exhttp"

	"go.mau.fi/mautrix-meta/pkg/instameow"
	"go.mau.fi/mautrix-meta/pkg/instameow/slidetypes"
	"go.mau.fi/mautrix-meta/pkg/messagix/cookies"
	"go.mau.fi/mautrix-meta/pkg/messagix/httpclient"
	"go.mau.fi/mautrix-meta/pkg/messagix/table"
	"go.mau.fi/mautrix-meta/pkg/messagix/types"
)

const (
	maxRecentMessages      = 4096
	maxMessageThreadCache  = 8192
	recentMessageTTLms     = int64(10 * 60 * 1000)
	recentMessageSweepMs   = int64(60 * 1000)
)

// Client wraps the Instagram Direct (`instameow`) transport and thread/message caches.
type Client struct {
	IG       *instameow.Client
	Logger   zerolog.Logger
	OwnID    int64
	Platform types.Platform

	eventChan          chan *Event
	eventMu            sync.RWMutex
	eventsClosed       bool
	disconnectOnce     sync.Once
	connectMu          sync.Mutex
	lifecycleMu        sync.RWMutex
	disconnected       bool
	ctx                context.Context
	cancel             context.CancelFunc
	mu                 sync.RWMutex
	threadCache        map[int64]*Thread
	igThreadIDMap      map[int64]*instameow.ThreadIGIDs
	igThreadKeyByShort map[string]int64
	igMsgThreadMap     map[string]*instameow.ThreadIGIDs
	igMsgThreadOrder   []string
	recentMessages     map[string]int64
	recentMessagesMu   sync.Mutex
	recentMessageSweep int64
	connectionStatusMu sync.RWMutex
	transportFailure   transportFailureState
	connected          atomic.Bool
	everConnected      atomic.Bool
}

// ClientConfig configures a new Instagram Direct bridge client.
type ClientConfig struct {
	Cookies  map[string]string `json:"cookies"`
	Platform string            `json:"platform,omitempty"` // Must be empty or "instagram"
	LogLevel string            `json:"logLevel,omitempty"`
}

// NewClient creates a new Instagram Direct client using session cookies.
func NewClient(cfg *ClientConfig) (*Client, error) {
	if cfg == nil {
		return nil, errors.New("client config is required")
	}
	platform := strings.ToLower(strings.TrimSpace(cfg.Platform))
	if platform != "" && platform != "instagram" {
		return nil, fmt.Errorf("unsupported platform %q: only instagram is supported", cfg.Platform)
	}

	cks := &cookies.Cookies{Platform: types.Instagram}
	valMap := make(map[cookies.MetaCookieName]string, len(cfg.Cookies))
	for k, v := range cfg.Cookies {
		valMap[cookies.MetaCookieName(k)] = v
	}
	cks.UpdateValues(valMap)

	logLevel := zerolog.InfoLevel
	switch strings.ToLower(strings.TrimSpace(cfg.LogLevel)) {
	case "debug":
		logLevel = zerolog.DebugLevel
	case "trace":
		logLevel = zerolog.TraceLevel
	case "warn":
		logLevel = zerolog.WarnLevel
	case "error":
		logLevel = zerolog.ErrorLevel
	case "none", "disabled":
		logLevel = zerolog.Disabled
	}
	zerolog.SetGlobalLevel(logLevel)
	console := zerolog.ConsoleWriter{Out: os.Stderr}
	logger := zerolog.New(newRedactingLogWriter(console)).With().Timestamp().Logger()

	ctx, cancel := context.WithCancel(context.Background())

	client := &Client{
		Logger:             logger,
		Platform:           types.Instagram,
		eventChan:          make(chan *Event, 128),
		ctx:                ctx,
		cancel:             cancel,
		threadCache:        make(map[int64]*Thread),
		igThreadIDMap:      make(map[int64]*instameow.ThreadIGIDs),
		igThreadKeyByShort: make(map[string]int64),
		igMsgThreadMap:     make(map[string]*instameow.ThreadIGIDs),
		recentMessages:     make(map[string]int64),
	}

	client.IG = instameow.NewClient(instameow.ClientParams{
		Cookies:      cks,
		Log:          logger,
		Settings:     exhttp.ClientSettings{},
		EventHandler: client.handleIGEvent,
	})

	return client, nil
}

func (c *Client) opContext() context.Context {
	c.lifecycleMu.RLock()
	ctx := c.ctx
	c.lifecycleMu.RUnlock()
	if ctx == nil {
		return context.Background()
	}
	return ctx
}

// Connect authenticates the Instagram web session, fetches initial mailbox threads,
// and starts the realtime DGW WebSocket listener.
func (c *Client) Connect() (_ *UserInfo, _ *InitialData, err error) {
	c.connectMu.Lock()
	defer c.connectMu.Unlock()
	c.connected.Store(false)
	if err := c.lifecycleError(); err != nil {
		return nil, nil, err
	}
	c.markTransportConnecting()
	defer func() {
		if errors.Is(err, context.Canceled) {
			c.clearTransportFailure()
		} else if err != nil {
			c.setTransportFailure(synchronousConnectionFailure(err))
		}
	}()

	if c.IG == nil {
		return nil, nil, errors.New("instagram client is not initialized")
	}
	if !c.IG.GetCookies().IsLoggedIn() {
		return nil, nil, httpclient.ErrTokenInvalidated
	}

	currentUser, mailbox, err := c.IG.LoadIndex(c.ctx)
	if err != nil {
		return nil, nil, err
	}

	ownID := c.IG.GetOwnFBID()
	if ownID == 0 && currentUser != nil && currentUser.ID != "" {
		ownID, _ = strconv.ParseInt(currentUser.ID, 10, 64)
	}
	if ownID == 0 && c.IG.GetCookies() != nil {
		ownID = c.IG.GetCookies().GetUserID()
	}

	userInfo := &UserInfo{
		ID: ownID,
	}
	if currentUser != nil {
		userInfo.Name = currentUser.GetName()
		userInfo.Username = currentUser.GetUsername()
	}
	c.OwnID = userInfo.ID

	initialData := &InitialData{}
	if mailbox != nil {
		for _, wrapped := range mailbox.PinnedThreadsV2 {
			if t := c.cacheIGThreadInfo(wrapped.AsIGDirectThread); t != nil {
				initialData.Threads = append(initialData.Threads, t)
			}
		}
		for _, edge := range mailbox.ThreadsByFolder.Edges {
			if t := c.cacheIGThreadInfo(edge.Node.AsIGDirectThread); t != nil {
				initialData.Threads = append(initialData.Threads, t)
			}
		}
	}

	if err := c.lifecycleError(); err != nil {
		return nil, nil, err
	}

	c.connected.Store(true)
	c.everConnected.Store(true)
	c.clearTransportFailure()
	c.emitEvent(EventTypeReady, map[string]any{
		"isNewSession": false,
	})

	go c.IG.Connect(c.ctx)

	return userInfo, initialData, nil
}

// Disconnect stops the Instagram DGW listener and closes the event stream.
func (c *Client) Disconnect() {
	c.disconnectOnce.Do(func() {
		c.connected.Store(false)
		c.clearTransportFailure()
		if c.cancel != nil {
			c.cancel()
		}

		c.lifecycleMu.Lock()
		c.disconnected = true
		c.lifecycleMu.Unlock()

		c.connectMu.Lock()
		c.lifecycleMu.RLock()
		igClient := c.IG
		c.lifecycleMu.RUnlock()
		c.connectMu.Unlock()

		if igClient != nil {
			igClient.Disconnect()
		}
		c.clearTransportFailure()

		c.eventMu.Lock()
		if !c.eventsClosed {
			c.eventsClosed = true
			close(c.eventChan)
		}
		c.eventMu.Unlock()
	})
}

func (c *Client) lifecycleError() error {
	c.lifecycleMu.RLock()
	defer c.lifecycleMu.RUnlock()
	if c.disconnected || c.ctx == nil {
		return context.Canceled
	}
	return c.ctx.Err()
}

// IsConnected returns true when the Instagram Direct session and transport are active.
func (c *Client) IsConnected() bool {
	if c == nil {
		return false
	}
	c.lifecycleMu.RLock()
	defer c.lifecycleMu.RUnlock()
	return !c.disconnected && c.IG != nil && c.ctx != nil && c.ctx.Err() == nil && c.connected.Load()
}

// Events returns the outbound bridge event channel.
func (c *Client) Events() <-chan *Event {
	return c.eventChan
}

func (c *Client) cacheThread(thread *Thread) {
	if thread == nil || thread.ID == 0 {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.threadCache == nil {
		c.threadCache = make(map[int64]*Thread)
	}
	c.threadCache[thread.ID] = thread
}

func (c *Client) threadMeta(threadID int64) (string, int) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if t, ok := c.threadCache[threadID]; ok && t != nil {
		return t.Name, t.Type
	}
	return "", int(table.ONE_TO_ONE)
}

func (c *Client) emitEvent(eventType EventType, data any) {
	c.eventMu.RLock()
	defer c.eventMu.RUnlock()
	if c.eventsClosed {
		return
	}
	evt := &Event{
		Type:      eventType,
		Data:      data,
		Timestamp: timeNowMs(),
	}
	select {
	case c.eventChan <- evt:
	default:
	}
}

func (c *Client) cacheIGThreadInfo(info *slidetypes.ThreadInfo) *Thread {
	if info == nil {
		return nil
	}
	threadKey := info.ThreadKey
	if threadKey == 0 && info.ID != "" {
		threadKey, _ = strconv.ParseInt(info.ID, 10, 64)
	}
	if threadKey == 0 && info.ThreadFBID != "" {
		threadKey, _ = strconv.ParseInt(info.ThreadFBID, 10, 64)
	}
	if threadKey == 0 {
		return nil
	}

	shortID := info.ID
	if shortID == "" {
		shortID = info.ThreadFBID
	}
	if shortID == "" {
		shortID = strconv.FormatInt(threadKey, 10)
	}
	longID := info.ThreadID
	if longID == "" {
		longID = shortID
	}

	c.mu.Lock()
	if c.igThreadIDMap == nil {
		c.igThreadIDMap = make(map[int64]*instameow.ThreadIGIDs)
	}
	if c.igThreadKeyByShort == nil {
		c.igThreadKeyByShort = make(map[string]int64)
	}
	ids := &instameow.ThreadIGIDs{
		ShortID: shortID,
		LongID:  longID,
	}
	c.igThreadIDMap[threadKey] = ids
	if shortKey, err := strconv.ParseInt(shortID, 10, 64); err == nil && shortKey != 0 {
		c.igThreadIDMap[shortKey] = ids
	}
	c.igThreadKeyByShort[shortID] = threadKey
	if longID != "" {
		c.igThreadKeyByShort[longID] = threadKey
	}
	c.mu.Unlock()

	threadType := int(table.ONE_TO_ONE)
	if info.IsGroup {
		threadType = int(table.GROUP_THREAD)
	}
	title := info.ThreadTitle
	if title == "" && len(info.Users) > 0 {
		if info.Users[0].FullName != "" {
			title = info.Users[0].FullName
		} else {
			title = info.Users[0].Username
		}
	}

	thread := &Thread{
		ID:                      threadKey,
		Type:                    threadType,
		Name:                    title,
		LastActivityTimestampMs: info.LastActivityTimestampMS.UnixMilli(),
	}
	c.cacheThread(thread)
	return thread
}

func (c *Client) resolveIGThreadIDs(ctx context.Context, threadKey int64) (*instameow.ThreadIGIDs, error) {
	if threadKey == 0 {
		return nil, errors.New("thread ID is required")
	}
	c.mu.RLock()
	if c.igThreadIDMap != nil {
		if ids, ok := c.igThreadIDMap[threadKey]; ok && ids != nil && ids.ShortID != "" {
			c.mu.RUnlock()
			return ids, nil
		}
	}
	c.mu.RUnlock()

	if c.IG != nil {
		ids, err := c.IG.FetchThreadID(ctx, threadKey)
		if err == nil && ids != nil && ids.ShortID != "" {
			c.mu.Lock()
			if c.igThreadIDMap == nil {
				c.igThreadIDMap = make(map[int64]*instameow.ThreadIGIDs)
			}
			if c.igThreadKeyByShort == nil {
				c.igThreadKeyByShort = make(map[string]int64)
			}
			c.igThreadIDMap[threadKey] = ids
			c.igThreadKeyByShort[ids.ShortID] = threadKey
			if ids.LongID != "" {
				c.igThreadKeyByShort[ids.LongID] = threadKey
			}
			c.mu.Unlock()
			return ids, nil
		}

		if tResp, tErr := c.IG.GetThread(ctx, slidetypes.MakeGetThreadInfoRequest(strconv.FormatInt(threadKey, 10))); tErr == nil && tResp != nil && tResp.ThreadInfo.AsIGDirectThread != nil {
			c.cacheIGThreadInfo(tResp.ThreadInfo.AsIGDirectThread)
			c.mu.RLock()
			cached := c.igThreadIDMap[threadKey]
			c.mu.RUnlock()
			if cached != nil && cached.ShortID != "" {
				return cached, nil
			}
		}

		if mbResp, mbErr := c.IG.GetMailbox(ctx); mbErr == nil && mbResp.GetMailbox() != nil {
			mb := mbResp.GetMailbox()
			for _, wrapped := range mb.PinnedThreadsV2 {
				c.cacheIGThreadInfo(wrapped.AsIGDirectThread)
			}
			for _, edge := range mb.ThreadsByFolder.Edges {
				c.cacheIGThreadInfo(edge.Node.AsIGDirectThread)
			}
			cursor := mb.ThreadsByFolder.PageInfo.EndCursor
			hasNext := mb.ThreadsByFolder.PageInfo.HasNextPage
			for page := 0; page < 3 && hasNext && cursor != ""; page++ {
				c.mu.RLock()
				found := c.igThreadIDMap[threadKey]
				c.mu.RUnlock()
				if found != nil && found.ShortID != "" {
					return found, nil
				}
				pResp, pErr := c.IG.PaginateMailbox(ctx, slidetypes.MakePaginateMailboxRequest(c.OwnID, cursor, "INBOX", nil))
				if pErr != nil || pResp == nil || pResp.Mailbox == nil {
					break
				}
				for _, edge := range pResp.Mailbox.ThreadsByFolder.Edges {
					c.cacheIGThreadInfo(edge.Node.AsIGDirectThread)
				}
				cursor = pResp.Mailbox.ThreadsByFolder.PageInfo.EndCursor
				hasNext = pResp.Mailbox.ThreadsByFolder.PageInfo.HasNextPage
			}
			c.mu.RLock()
			if found := c.igThreadIDMap[threadKey]; found != nil && found.ShortID != "" {
				c.mu.RUnlock()
				return found, nil
			}
			c.mu.RUnlock()
		}
	}

	shortStr := strconv.FormatInt(threadKey, 10)
	return &instameow.ThreadIGIDs{
		ShortID: shortStr,
		LongID:  shortStr,
	}, nil
}

func (c *Client) resolveIGThreadKey(shortOrLongID string) int64 {
	if shortOrLongID == "" {
		return 0
	}
	c.mu.RLock()
	if c.igThreadKeyByShort != nil {
		if key, ok := c.igThreadKeyByShort[shortOrLongID]; ok && key != 0 {
			c.mu.RUnlock()
			return key
		}
	}
	c.mu.RUnlock()

	if c.IG != nil {
		resp, err := c.IG.GetThread(c.opContext(), slidetypes.MakeGetThreadInfoRequest(shortOrLongID))
		if err == nil && resp != nil && resp.ThreadInfo.AsIGDirectThread != nil {
			if t := c.cacheIGThreadInfo(resp.ThreadInfo.AsIGDirectThread); t != nil {
				return t.ID
			}
		}
	}
	if parsed, err := strconv.ParseInt(shortOrLongID, 10, 64); err == nil && parsed != 0 {
		return parsed
	}
	return 0
}

func (c *Client) rememberIGMessageThread(messageID, shortID, longID string) {
	if messageID == "" {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.igMsgThreadMap == nil {
		c.igMsgThreadMap = make(map[string]*instameow.ThreadIGIDs)
	}
	if _, exists := c.igMsgThreadMap[messageID]; !exists {
		if len(c.igMsgThreadOrder) >= maxMessageThreadCache {
			oldest := c.igMsgThreadOrder[0]
			c.igMsgThreadOrder = c.igMsgThreadOrder[1:]
			delete(c.igMsgThreadMap, oldest)
		}
		c.igMsgThreadOrder = append(c.igMsgThreadOrder, messageID)
	}
	c.igMsgThreadMap[messageID] = &instameow.ThreadIGIDs{
		ShortID: shortID,
		LongID:  longID,
	}
}

func (c *Client) lookupIGMessageThread(messageID string) *instameow.ThreadIGIDs {
	if messageID == "" {
		return nil
	}
	c.mu.RLock()
	defer c.mu.RUnlock()
	if c.igMsgThreadMap == nil {
		return nil
	}
	return c.igMsgThreadMap[messageID]
}

