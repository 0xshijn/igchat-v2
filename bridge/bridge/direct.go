package bridge

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"go.mau.fi/util/jsontime"
	"go.mau.fi/util/ptr"
	"go.mau.fi/util/variationselector"

	"go.mau.fi/mautrix-meta/pkg/instameow/slidetypes"
	"go.mau.fi/mautrix-meta/pkg/messagix/methods"
	"go.mau.fi/mautrix-meta/pkg/messagix/responses"
	"go.mau.fi/mautrix-meta/pkg/messagix/socket"
	"go.mau.fi/mautrix-meta/pkg/messagix/table"
	"go.mau.fi/mautrix-meta/pkg/messagix/types"
)

const (
	DeliveryStatusAcknowledged = "acknowledged"
)

// SendMessageOptions describes an Instagram Direct text or uploaded-media send.
type SendMessageOptions struct {
	ThreadID        int64   `json:"threadId"`
	Text            string  `json:"text"`
	ReplyToID       string  `json:"replyToId,omitempty"`
	MentionIDs      []int64 `json:"mentionIds,omitempty"`
	MentionOffsets  []int   `json:"mentionOffsets,omitempty"`
	MentionLengths  []int   `json:"mentionLengths,omitempty"`
	AttachmentFbIds []int64 `json:"attachmentFbIds,omitempty"`
}

// SendMessageResult summarizes the sent message returned by Slide GraphQL.
type SendMessageResult struct {
	MessageID      string `json:"messageId"`
	TimestampMs    int64  `json:"timestampMs"`
	DeliveryStatus string `json:"deliveryStatus,omitempty"`
}

// SearchUsersOptions configures Instagram Direct user search.
type SearchUsersOptions struct {
	Query string `json:"query"`
}

// SearchUser represents one Instagram user search hit.
type SearchUser struct {
	ID                int64  `json:"id"`
	PK                string `json:"pk,omitempty"`
	Name              string `json:"name"`
	Username          string `json:"username"`
	ProfilePictureUrl string `json:"profilePictureUrl,omitempty"`
	IsVerified        bool   `json:"isVerified,omitempty"`
}

// GetUserInfoOptions configures user lookup by messaging/user ID.
type GetUserInfoOptions struct {
	UserID int64 `json:"userId"`
}

// ContactInfo represents Instagram participant/contact metadata.
type ContactInfo struct {
	ID                int64  `json:"id"`
	Name              string `json:"name"`
	FirstName         string `json:"firstName,omitempty"`
	Username          string `json:"username,omitempty"`
	ProfilePictureUrl string `json:"profilePictureUrl,omitempty"`
	IsVerified        bool   `json:"isVerified,omitempty"`
	CanViewerMessage  bool   `json:"canViewerMessage,omitempty"`
}

// MuteThreadOptions configures thread notification muting.
type MuteThreadOptions struct {
	ThreadID    int64 `json:"threadId"`
	MuteSeconds int64 `json:"muteSeconds"` // -1 for forever, 0 to unmute
}

// RenameThreadOptions configures group thread renaming.
type RenameThreadOptions struct {
	ThreadID int64  `json:"threadId"`
	NewName  string `json:"newName"`
}

// DeleteThreadOptions configures thread hiding/deletion.
type DeleteThreadOptions struct {
	ThreadID   int64 `json:"threadId"`
	MarkAsSpam bool  `json:"markAsSpam,omitempty"`
}

// ThreadDetail holds detailed metadata, participants, and recent messages of a thread.
type ThreadDetail struct {
	ID           int64          `json:"id"`
	ShortID      string         `json:"shortId,omitempty"`
	LongID       string         `json:"longId,omitempty"`
	Name         string         `json:"name"`
	IsGroup      bool           `json:"isGroup"`
	IsMuted      bool           `json:"isMuted"`
	IsPinned     bool           `json:"isPinned"`
	Folder       string         `json:"folder,omitempty"`
	AdminUserIDs []string       `json:"adminUserIds,omitempty"`
	Participants []*ContactInfo `json:"participants,omitempty"`
	Messages     []*Message     `json:"messages,omitempty"`
}

// ForwardMessageOptions configures forwarding an Instagram Direct message.
type ForwardMessageOptions struct {
	SourceThreadID int64  `json:"sourceThreadId"`
	TargetThreadID int64  `json:"targetThreadId"`
	MessageID      string `json:"messageId,omitempty"`
	Text           string `json:"text,omitempty"`
}

// FetchedMediaInfo holds metadata and direct CDN URLs for an Instagram post/reel.
type FetchedMediaInfo struct {
	ID            string   `json:"id"`
	Shortcode     string   `json:"shortcode"`
	MediaType     int      `json:"mediaType"`
	Author        string   `json:"author,omitempty"`
	Caption       string   `json:"caption,omitempty"`
	LikeCount     int      `json:"likeCount"`
	PlayCount     int      `json:"playCount"`
	VideoDuration float64  `json:"videoDuration,omitempty"`
	URLs          []string `json:"urls"`
}

// WebProfilePost represents a recent timeline post from a user's profile.
type WebProfilePost struct {
	ID           string `json:"id"`
	Shortcode    string `json:"shortcode"`
	URL          string `json:"url"`
	DisplayURL   string `json:"displayUrl,omitempty"`
	Caption      string `json:"caption,omitempty"`
	IsVideo      bool   `json:"isVideo"`
	LikeCount    int    `json:"likeCount"`
	CommentCount int    `json:"commentCount"`
	TakenAt      int    `json:"takenAt,omitempty"`
}

// WebProfileInfo holds comprehensive profile details for an Instagram user.
type WebProfileInfo struct {
	ID                string            `json:"id"`
	MessagingID       int64             `json:"messagingId,omitempty"`
	Username          string            `json:"username"`
	FullName          string            `json:"fullName"`
	Biography         string            `json:"biography,omitempty"`
	ExternalURL       string            `json:"externalUrl,omitempty"`
	ProfilePicURL     string            `json:"profilePicUrl,omitempty"`
	ProfilePicURLHD   string            `json:"profilePicUrlHd,omitempty"`
	IsPrivate         bool              `json:"isPrivate"`
	IsVerified        bool              `json:"isVerified"`
	IsBusinessAccount bool              `json:"isBusinessAccount"`
	FollowerCount     int               `json:"followerCount"`
	FollowingCount    int               `json:"followingCount"`
	PostCount         int               `json:"postCount"`
	RecentPosts       []*WebProfilePost `json:"recentPosts,omitempty"`
}

// StoryItemInfo holds metadata and media URL for a single Instagram story item.
type StoryItemInfo struct {
	ID            string  `json:"id"`
	Shortcode     string  `json:"shortcode,omitempty"`
	MediaType     int     `json:"mediaType"`
	URL           string  `json:"url"`
	PreviewURL    string  `json:"previewUrl,omitempty"`
	TakenAt       int     `json:"takenAt"`
	ExpiringAt    int     `json:"expiringAt,omitempty"`
	VideoDuration float64 `json:"videoDuration,omitempty"`
	Caption       string  `json:"caption,omitempty"`
}

// FetchedStoriesResult holds all active story items for an Instagram user or highlight.
type FetchedStoriesResult struct {
	UserID   string           `json:"userId"`
	Username string           `json:"username,omitempty"`
	FullName string           `json:"fullName,omitempty"`
	Count    int              `json:"count"`
	Items    []*StoryItemInfo `json:"items"`
}

// PaginatedInboxResult holds a page of Instagram threads and pagination state.
type PaginatedInboxResult struct {
	Threads     []*Thread `json:"threads"`
	NextCursor  string    `json:"nextCursor,omitempty"`
	HasNextPage bool      `json:"hasNextPage"`
}

// PaginatedMessagesResult holds a page of thread messages and pagination state.
type PaginatedMessagesResult struct {
	ThreadID    int64      `json:"threadId"`
	Messages    []*Message `json:"messages"`
	NextCursor  string     `json:"nextCursor,omitempty"`
	HasNextPage bool       `json:"hasNextPage"`
}

// SendMessage sends a text message or uploaded media attachment to an Instagram Direct thread.
func (c *Client) SendMessage(opts *SendMessageOptions) (*SendMessageResult, error) {
	if opts == nil {
		return nil, errors.New("sendMessage options are required")
	}
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	ids, err := c.resolveIGThreadIDs(ctx, opts.ThreadID)
	if err != nil {
		return nil, err
	}

	otid := strconv.FormatInt(methods.GenerateEpochID(), 10)
	var replyToID *string
	if opts.ReplyToID != "" {
		replyToID = &opts.ReplyToID
	}

	var mentions socket.Mentions
	for i, id := range opts.MentionIDs {
		offset, length := 0, 0
		if i < len(opts.MentionOffsets) {
			offset = opts.MentionOffsets[i]
		}
		if i < len(opts.MentionLengths) {
			length = opts.MentionLengths[i]
		}
		mType := socket.MentionTypePerson
		targetID := id
		if id == -1 || (opts.ThreadID != 0 && id == opts.ThreadID) {
			mType = socket.MentionTypeThread
			if shortInt, sErr := strconv.ParseInt(ids.ShortID, 10, 64); sErr == nil && shortInt != 0 {
				targetID = shortInt
			} else {
				targetID = opts.ThreadID
			}
		}
		mentions = append(mentions, socket.Mention{
			ID:     targetID,
			Offset: offset,
			Length: length,
			Type:   mType,
		})
	}
	realMentions, mentionedUserIDs, commands := slidetypes.SocketMentionsToInput(mentions)
	if len(commands) == 0 && strings.Contains(strings.ToLower(opts.Text), "@everyone") {
		idx := strings.Index(strings.ToLower(opts.Text), "@everyone")
		targetThreadID := opts.ThreadID
		if shortInt, sErr := strconv.ParseInt(ids.ShortID, 10, 64); sErr == nil && shortInt != 0 {
			targetThreadID = shortInt
		}
		commands = append(commands, slidetypes.InputCommand{
			Offset:           idx,
			Length:           len("@everyone"),
			Type:             "EVERYONE",
			UserOrThreadFBID: targetThreadID,
		})
	}

	if len(opts.AttachmentFbIds) > 0 {
		var lastSent slidetypes.SentMessage
		for _, attID := range opts.AttachmentFbIds {
			resp, sendErr := c.IG.SendMedia(ctx, &slidetypes.SendMediaRequest{
				AttachmentFBID:     strconv.FormatInt(attID, 10),
				ThreadID:           ids.ShortID,
				OfflineThreadingID: otid,
				ReplyToMessageID:   replyToID,
			})
			if sendErr != nil {
				return nil, sendErr
			}
			lastSent = resp.GetMessage()
		}
		msgID := lastSent.ID
		if msgID == "" {
			msgID = lastSent.MessageID
		}
		if msgID == "" {
			msgID = otid
		}
		tsMs := lastSent.TimestampMS.UnixMilli()
		if tsMs == 0 {
			tsMs = timeNowMs()
		}
		c.rememberIGMessageThread(msgID, ids.ShortID, ids.LongID)
		return &SendMessageResult{
			MessageID:      msgID,
			TimestampMs:    tsMs,
			DeliveryStatus: DeliveryStatusAcknowledged,
		}, nil
	}

	req := &slidetypes.SendTextRequest{
		IGThreadIGID:       &ids.ShortID,
		OfflineThreadingID: otid,
		ReplyToMessageID:   replyToID,
		Text:               slidetypes.SensitiveString{Value: opts.Text},
		Mentions:           realMentions,
		MentionedUserIDs:   mentionedUserIDs,
		Commands:           commands,
		SendAttribution:    ptr.Ptr("igd_web_chat_tab:in_thread"),
	}
	resp, err := c.IG.SendMessage(ctx, req)
	if err != nil {
		return nil, err
	}
	sent := resp.GetMessage()
	msgID := sent.ID
	if msgID == "" {
		msgID = sent.MessageID
	}
	if msgID == "" {
		msgID = otid
	}
	tsMs := sent.TimestampMS.UnixMilli()
	if tsMs == 0 {
		tsMs = timeNowMs()
	}
	c.rememberIGMessageThread(msgID, ids.ShortID, ids.LongID)
	return &SendMessageResult{
		MessageID:      msgID,
		TimestampMs:    tsMs,
		DeliveryStatus: DeliveryStatusAcknowledged,
	}, nil
}

// SendReaction adds or removes (empty emoji) a reaction on a message.
func (c *Client) SendReaction(threadID int64, messageID, emoji string) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	var shortID string
	if cached := c.lookupIGMessageThread(messageID); cached != nil && cached.ShortID != "" {
		shortID = cached.ShortID
	} else {
		ids, err := c.resolveIGThreadIDs(ctx, threadID)
		if err != nil {
			return err
		}
		shortID = ids.ShortID
	}
	status := slidetypes.ReactionStatusCreated
	cleanEmoji := variationselector.Remove(emoji)
	if cleanEmoji == "" {
		status = slidetypes.ReactionStatusDeleted
	}
	_, err := c.IG.SendReaction(ctx, &slidetypes.CreateReactionRequest{
		Input: slidetypes.ReactionInput{
			Emoji:          cleanEmoji,
			ItemID:         "",
			MessageID:      messageID,
			ReactionStatus: status,
			ThreadID:       shortID,
		},
	})
	return err
}

// EditMessage edits an existing Instagram Direct message.
func (c *Client) EditMessage(threadID int64, messageID, newText string) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	var shortID string
	if cached := c.lookupIGMessageThread(messageID); cached != nil && cached.ShortID != "" {
		shortID = cached.ShortID
	} else if threadID != 0 {
		ids, err := c.resolveIGThreadIDs(ctx, threadID)
		if err != nil {
			return err
		}
		shortID = ids.ShortID
	}
	_, err := c.IG.EditMessage(ctx, &slidetypes.EditMessageRequest{
		ThreadID:           shortID,
		TargetItemID:       "",
		Body:               slidetypes.SensitiveString{Value: newText},
		OfflineThreadingID: strconv.FormatInt(methods.GenerateEpochID(), 10),
		TargetMessageID:    messageID,
	})
	return err
}

// UnsendMessage unsends an Instagram Direct message.
func (c *Client) UnsendMessage(threadID int64, messageID string) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	var longID string
	if cached := c.lookupIGMessageThread(messageID); cached != nil && cached.LongID != "" {
		longID = cached.LongID
	} else if threadID != 0 {
		ids, err := c.resolveIGThreadIDs(ctx, threadID)
		if err != nil {
			return err
		}
		longID = ids.LongID
	}
	_, err := c.IG.UnsendMessage(ctx, &slidetypes.UnsendMessageRequest{
		MessageID: messageID,
		SendData: slidetypes.SendData{
			ThreadID: longID,
		},
	})
	return err
}

// SendTypingIndicator sends typing state over Instagram DGW mqttbypass.
func (c *Client) SendTypingIndicator(threadID int64, isTyping bool) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	ids, err := c.resolveIGThreadIDs(ctx, threadID)
	if err != nil {
		return err
	}
	return c.IG.SetTyping(ctx, ids.ShortID, isTyping)
}

// MarkRead marks a thread (or message) as seen.
func (c *Client) MarkRead(threadID int64, watermarkTs int64) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	ids, err := c.resolveIGThreadIDs(ctx, threadID)
	if err != nil {
		return err
	}
	var messageID string
	resp, tErr := c.IG.GetThread(ctx, slidetypes.MakeGetThreadInfoRequest(ids.ShortID))
	if tErr == nil && resp != nil && resp.ThreadInfo.AsIGDirectThread != nil && resp.ThreadInfo.AsIGDirectThread.SlideMessages != nil {
		edges := resp.ThreadInfo.AsIGDirectThread.SlideMessages.Edges
		if len(edges) > 0 && edges[0].Node != nil {
			lastMsg := edges[0].Node
			messageID = lastMsg.ID
			if messageID == "" {
				messageID = lastMsg.MessageID
			}
			if watermarkTs == 0 {
				watermarkTs = lastMsg.TimestampMS.UnixMilli()
			}
		}
	}
	if messageID == "" {
		return nil
	}
	emptyItemID := ""
	_, err = c.IG.MarkRead(ctx, &slidetypes.MarkReadRequest{
		Metadata: slidetypes.MarkReadMetadata{
			IGThreadIGID: ids.LongID,
		},
		Data: slidetypes.MarkReadData{
			MessageID: messageID,
			ItemID:    &emptyItemID,
		},
	})
	if err != nil {
		return err
	}
	if watermarkTs > 0 {
		_, _ = c.IG.MarkReadValidation(ctx, &slidetypes.MarkReadRequest{
			Metadata: slidetypes.MarkReadMetadata{
				IGThreadIGID: ids.LongID,
			},
			Data: slidetypes.MarkReadData{
				MessageID:          messageID,
				MessageTimestampMS: jsontime.UnixMilliString{Time: time.UnixMilli(watermarkTs)},
			},
		})
	}
	return nil
}

// PinMessage pins or unpins a message in a thread.
func (c *Client) PinMessage(threadID int64, messageID string, pin bool) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	var shortID string
	if cached := c.lookupIGMessageThread(messageID); cached != nil && cached.ShortID != "" {
		shortID = cached.ShortID
	} else if threadID != 0 {
		ids, err := c.resolveIGThreadIDs(ctx, threadID)
		if err != nil {
			return err
		}
		shortID = ids.ShortID
	}
	req := &slidetypes.PinMessageRequest{
		ThreadID:  shortID,
		MessageID: messageID,
	}
	if pin {
		_, err := c.IG.PinMessage(ctx, req)
		return err
	}
	_, err := c.IG.UnpinMessage(ctx, req)
	return err
}

// PinThread pins or unpins a conversation thread.
func (c *Client) PinThread(threadID int64, pin bool) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	ids, err := c.resolveIGThreadIDs(ctx, threadID)
	if err != nil {
		return err
	}
	_, err = c.IG.PinThread(ctx, &slidetypes.PinThreadRequest{
		ThreadID: ids.ShortID,
		Pin:      pin,
	})
	return err
}

// MuteThread mutes or unmutes a thread (-1 permanent, 0 unmute, >0 seconds).
func (c *Client) MuteThread(opts *MuteThreadOptions) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	ids, err := c.resolveIGThreadIDs(ctx, opts.ThreadID)
	if err != nil {
		return err
	}
	_, err = c.IG.MuteThread(ctx, &slidetypes.MuteThreadRequest{
		ThreadID:           ids.ShortID,
		MuteSeconds:        int(opts.MuteSeconds),
		OfflineThreadingID: strconv.FormatInt(methods.GenerateEpochID(), 10),
	})
	return err
}

// RenameThread renames an Instagram group thread.
func (c *Client) RenameThread(opts *RenameThreadOptions) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	ids, err := c.resolveIGThreadIDs(ctx, opts.ThreadID)
	if err != nil {
		return err
	}
	return c.IG.EditGroupTitle(ctx, ids.ShortID, opts.NewName)
}

// DeleteThread hides/deletes a conversation thread.
func (c *Client) DeleteThread(opts *DeleteThreadOptions) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	ids, err := c.resolveIGThreadIDs(ctx, opts.ThreadID)
	if err != nil {
		return err
	}
	_, err = c.IG.DeleteThread(ctx, &slidetypes.DeleteThreadRequest{
		ThreadID:   ids.ShortID,
		MarkAsSpam: opts.MarkAsSpam,
	})
	if err == nil {
		c.mu.Lock()
		delete(c.threadCache, opts.ThreadID)
		c.mu.Unlock()
	}
	return err
}

// AcceptMessageRequest moves a pending message request into the primary inbox.
func (c *Client) AcceptMessageRequest(threadID int64) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	ids, err := c.resolveIGThreadIDs(ctx, threadID)
	if err != nil {
		return err
	}
	_, err = c.IG.AcceptMessageRequest(ctx, &slidetypes.AcceptMessageRequestRequest{
		ThreadID:           ids.ShortID,
		OfflineThreadingID: strconv.FormatInt(methods.GenerateEpochID(), 10),
	})
	return err
}

// SearchUsers searches Instagram users via `IGDOmniPickerSearchResultsListQuery`.
func (c *Client) SearchUsers(opts *SearchUsersOptions) ([]*SearchUser, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	resp, err := c.IG.SearchUsers(ctx, strings.TrimSpace(opts.Query))
	if err != nil {
		return nil, err
	}
	out := make([]*SearchUser, 0)
	if resp != nil {
		for _, r := range resp.Data.Results {
			if r == nil {
				continue
			}
			id := r.InteropMessagingUserFBID
			if id == 0 && r.PK != "" {
				id, _ = strconv.ParseInt(r.PK, 10, 64)
			}
			out = append(out, &SearchUser{
				ID:                id,
				PK:                r.PK,
				Name:              r.FullName,
				Username:          r.Username,
				ProfilePictureUrl: r.ProfilePicURL,
				IsVerified:        r.IsVerified,
			})
		}
	}
	return out, nil
}

// GetUserInfo looks up an Instagram user by messaging/user ID.
func (c *Client) GetUserInfo(opts *GetUserInfoOptions) (*ContactInfo, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	resp, err := c.IG.GetUserForNewDM(ctx, opts.UserID)
	if err == nil && resp != nil && resp.Data != nil {
		u := resp.Data
		id := u.InteropMessagingUserFBID
		if id == 0 {
			id = opts.UserID
		}
		return &ContactInfo{
			ID:                id,
			Name:              u.FullName,
			Username:          u.Username,
			ProfilePictureUrl: u.ProfilePicURL,
			IsVerified:        u.IsVerified,
			CanViewerMessage:  true,
		}, nil
	}
	profileResp, profErr := c.IG.GetProfile(ctx, strconv.FormatInt(opts.UserID, 10))
	if profErr == nil && profileResp != nil && profileResp.User != nil {
		u := profileResp.User
		id := u.InteropMessagingUserFBID
		if id == 0 {
			id = opts.UserID
		}
		return &ContactInfo{
			ID:                id,
			Name:              u.FullName,
			Username:          u.Username,
			ProfilePictureUrl: u.ProfilePicURL,
			IsVerified:        u.IsVerified,
			CanViewerMessage:  true,
		}, nil
	}
	if err != nil {
		return nil, err
	}
	return nil, fmt.Errorf("user not found: %d", opts.UserID)
}

// GetInbox returns the initial mailbox page of Instagram Direct threads.
func (c *Client) GetInbox() ([]*Thread, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	mailboxResp, err := c.IG.GetMailbox(c.opContext())
	if err != nil {
		return nil, err
	}
	mailbox := mailboxResp.GetMailbox()
	var threads []*Thread
	seen := make(map[int64]bool)
	if mailbox != nil {
		for _, wrapped := range mailbox.PinnedThreadsV2 {
			if t := c.cacheIGThreadInfo(wrapped.AsIGDirectThread); t != nil && !seen[t.ID] {
				seen[t.ID] = true
				threads = append(threads, t)
			}
		}
		for _, edge := range mailbox.ThreadsByFolder.Edges {
			if t := c.cacheIGThreadInfo(edge.Node.AsIGDirectThread); t != nil && !seen[t.ID] {
				seen[t.ID] = true
				threads = append(threads, t)
			}
		}
	}
	return threads, nil
}

// GetThreadInfo returns metadata, participants, and recent messages for a thread.
func (c *Client) GetThreadInfo(threadKey int64, messageLimit int) (*ThreadDetail, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	ids, err := c.resolveIGThreadIDs(ctx, threadKey)
	if err != nil {
		return nil, err
	}
	resp, err := c.IG.GetThread(ctx, slidetypes.MakeGetThreadInfoRequest(ids.ShortID))
	if err != nil {
		return nil, err
	}
	if resp == nil || resp.ThreadInfo.AsIGDirectThread == nil {
		return nil, fmt.Errorf("thread not found: %d", threadKey)
	}
	info := resp.ThreadInfo.AsIGDirectThread
	cachedThread := c.cacheIGThreadInfo(info)
	resolvedKey := threadKey
	if cachedThread != nil && cachedThread.ID != 0 {
		resolvedKey = cachedThread.ID
	}

	title := info.ThreadTitle
	if title == "" && cachedThread != nil {
		title = cachedThread.Name
	}

	participants := make([]*ContactInfo, 0, len(info.Users))
	for _, u := range info.Users {
		if u == nil {
			continue
		}
		uid := u.InteropMessagingUserFBID
		if uid == 0 && u.PK != "" {
			uid, _ = strconv.ParseInt(u.PK, 10, 64)
		}
		if uid == 0 && u.ID != "" {
			uid, _ = strconv.ParseInt(u.ID, 10, 64)
		}
		participants = append(participants, &ContactInfo{
			ID:                uid,
			Name:              u.FullName,
			Username:          u.Username,
			ProfilePictureUrl: u.ProfilePicURL,
			IsVerified:        u.IsVerified,
			CanViewerMessage:  true,
		})
	}

	if messageLimit <= 0 {
		messageLimit = 10
	}
	var messages []*Message
	if info.SlideMessages != nil {
		for _, edge := range info.SlideMessages.Edges {
			if len(messages) >= messageLimit {
				break
			}
			msg := edge.Node
			if msg == nil {
				continue
			}
			msgID := msg.ID
			if msgID == "" {
				msgID = msg.MessageID
			}
			var replyTo *ReplyTo
			if msg.RepliedToMessage != nil {
				replyID := msg.RepliedToMessage.ID
				if replyID == "" {
					replyID = msg.RepliedToMessage.MessageID
				}
				replyTo = &ReplyTo{
					MessageID: replyID,
					SenderID:  msg.RepliedToMessage.SenderFBID,
					Text:      msg.RepliedToMessage.TextBody,
				}
			} else if msg.RepliedToMessageID != "" {
				replyTo = &ReplyTo{
					MessageID: msg.RepliedToMessageID,
				}
			}
			messages = append(messages, &Message{
				ID:          msgID,
				ThreadID:    resolvedKey,
				ThreadName:  title,
				SenderID:    msg.SenderFBID,
				Text:        extractIGMessageText(msg),
				TimestampMs: msg.TimestampMS.UnixMilli(),
				Attachments: extractIGAttachments(msg.Content.Content),
				ReplyTo:     replyTo,
			})
		}
		cursor := info.SlideMessages.PageInfo.EndCursor
		if cursor == "" {
			cursor = info.SlideMessages.PageInfo.StartCursor
		}
		hasNext := info.SlideMessages.PageInfo.HasNextPage || info.SlideMessages.PageInfo.HasPreviousPage
		for page := 0; page < 3 && len(messages) < messageLimit && hasNext && cursor != ""; page++ {
			cCopy := cursor
			pResp, pErr := c.IG.PaginateMessages(ctx, &slidetypes.PaginateMessagesRequest{
				AfterCursor:             &cCopy,
				FirstN:                  20,
				ThreadID:                ids.ShortID,
				InitialMessagePageCount: 20,
			})
			if pErr != nil || pResp == nil || pResp.ThreadInfo.AsIGDirectThread == nil || pResp.ThreadInfo.AsIGDirectThread.Messages == nil {
				break
			}
			sm := pResp.ThreadInfo.AsIGDirectThread.Messages
			for _, edge := range sm.Edges {
				if len(messages) >= messageLimit {
					break
				}
				msg := edge.Node
				if msg == nil {
					continue
				}
				msgID := msg.ID
				if msgID == "" {
					msgID = msg.MessageID
				}
				messages = append(messages, &Message{
					ID:          msgID,
					ThreadID:    resolvedKey,
					ThreadName:  title,
					SenderID:    msg.SenderFBID,
					Text:        extractIGMessageText(msg),
					TimestampMs: msg.TimestampMS.UnixMilli(),
					Attachments: extractIGAttachments(msg.Content.Content),
				})
			}
			cursor = sm.PageInfo.EndCursor
			hasNext = sm.PageInfo.HasNextPage
		}
	}

	return &ThreadDetail{
		ID:           resolvedKey,
		ShortID:      ids.ShortID,
		LongID:       ids.LongID,
		Name:         title,
		IsGroup:      info.IsGroup,
		IsMuted:      ptr.Val(info.IsMuted),
		IsPinned:     ptr.Val(info.IsPin),
		Folder:       info.Folder,
		AdminUserIDs: info.AdminUserIDs,
		Participants: participants,
		Messages:     messages,
	}, nil
}

// GetMessageRequests returns pending Instagram Direct message requests.
func (c *Client) GetMessageRequests() ([]*Thread, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	pResp, err := c.IG.PaginateMailbox(c.opContext(), slidetypes.MakePaginateMailboxRequest(c.OwnID, "", "PENDING", nil))
	if err != nil {
		return nil, err
	}
	var threads []*Thread
	seen := make(map[int64]bool)
	if pResp != nil && pResp.Mailbox != nil {
		for _, edge := range pResp.Mailbox.ThreadsByFolder.Edges {
			if t := c.cacheIGThreadInfo(edge.Node.AsIGDirectThread); t != nil && !seen[t.ID] {
				seen[t.ID] = true
				threads = append(threads, t)
			}
		}
	}
	return threads, nil
}

// CreateGroup creates a new Instagram Direct group conversation.
func (c *Client) CreateGroup(recipientIDs []int64, title string) (*Thread, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	seen := make(map[int64]bool)
	recips := make([]string, 0, len(recipientIDs))
	for _, id := range recipientIDs {
		if id != 0 && id != c.OwnID && !seen[id] {
			seen[id] = true
			recips = append(recips, strconv.FormatInt(id, 10))
		}
	}
	if len(recips) < 2 {
		return nil, errors.New("instagram requires at least 2 other recipients to create a group chat")
	}
	resp, err := c.IG.CreateGroup(ctx, &slidetypes.CreateGroupRequest{
		RecipientFBIDs:     recips,
		OfflineThreadingID: strconv.FormatInt(methods.GenerateEpochID(), 10),
	})
	if err != nil {
		return nil, err
	}
	shortID := ""
	if resp != nil {
		shortID = resp.Data.ID
	}
	if shortID == "" {
		return nil, errors.New("instagram did not return a thread ID for the new group")
	}
	cleanTitle := strings.TrimSpace(title)
	if cleanTitle != "" {
		_ = c.IG.EditGroupTitle(ctx, shortID, cleanTitle)
	}
	initText := "New group created."
	if cleanTitle != "" {
		initText = fmt.Sprintf("Group %q created.", cleanTitle)
	}
	_, _ = c.IG.SendMessage(ctx, &slidetypes.SendTextRequest{
		IGThreadIGID:       &shortID,
		OfflineThreadingID: strconv.FormatInt(methods.GenerateEpochID(), 10),
		Text:               slidetypes.SensitiveString{Value: initText},
		SendAttribution:    ptr.Ptr("igd_web_chat_tab:in_thread"),
	})
	if tResp, tErr := c.IG.GetThread(ctx, slidetypes.MakeGetThreadInfoRequest(shortID)); tErr == nil && tResp != nil && tResp.ThreadInfo.AsIGDirectThread != nil {
		info := tResp.ThreadInfo.AsIGDirectThread
		if !info.IsGroup {
			return nil, errors.New("instagram returned a 1-on-1 DM instead of a group thread (at least 2 valid recipients are required)")
		}
		if cached := c.cacheIGThreadInfo(info); cached != nil {
			if cleanTitle != "" {
				cached.Name = cleanTitle
			}
			return cached, nil
		}
	}
	threadKey, _ := strconv.ParseInt(shortID, 10, 64)
	thread := &Thread{
		ID:   threadKey,
		Type: int(table.GROUP_THREAD),
		Name: cleanTitle,
	}
	if threadKey != 0 {
		c.cacheThread(thread)
	}
	return thread, nil
}

// AddGroupMembers adds Instagram users to a group thread.
func (c *Client) AddGroupMembers(threadID int64, userIDs []int64) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	ids, err := c.resolveIGThreadIDs(ctx, threadID)
	if err != nil {
		return err
	}
	userStrs := make([]string, 0, len(userIDs))
	for _, uid := range userIDs {
		if uid != 0 {
			userStrs = append(userStrs, strconv.FormatInt(uid, 10))
		}
	}
	_, err = c.IG.AddMembers(ctx, slidetypes.MakeAddMembersRequest(ids.ShortID, userStrs...))
	return err
}

// RemoveGroupMember removes an Instagram user from a group thread.
func (c *Client) RemoveGroupMember(threadID int64, userID int64) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	ids, err := c.resolveIGThreadIDs(ctx, threadID)
	if err != nil {
		return err
	}
	_, err = c.IG.RemoveMember(ctx, &slidetypes.RemoveMemberRequest{
		ThreadID: ids.ShortID,
		UserIGID: strconv.FormatInt(userID, 10),
	})
	return err
}

// ModifyGroupAdmins promotes or demotes admins in a group thread.
func (c *Client) ModifyGroupAdmins(threadID int64, userIDs []int64, promote bool) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	ids, err := c.resolveIGThreadIDs(ctx, threadID)
	if err != nil {
		return err
	}
	userStrs := make([]string, 0, len(userIDs))
	for _, uid := range userIDs {
		if uid != 0 {
			userStrs = append(userStrs, strconv.FormatInt(uid, 10))
		}
	}
	req := &slidetypes.ModifyAdminsRequest{
		ThreadID:  ids.ShortID,
		UserIGIDs: userStrs,
	}
	if promote {
		_, err = c.IG.AddAdmins(ctx, req)
		return err
	}
	_, err = c.IG.RemoveAdmins(ctx, req)
	return err
}

// LeaveGroup leaves a group conversation.
func (c *Client) LeaveGroup(threadID int64) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	ids, err := c.resolveIGThreadIDs(ctx, threadID)
	if err != nil {
		return err
	}
	_, err = c.IG.LeaveGroup(ctx, &slidetypes.LeaveThreadRequest{
		ThreadID: ids.ShortID,
	})
	return err
}

// SetUserBlocked blocks or unblocks an Instagram user.
func (c *Client) SetUserBlocked(userID string, blocked bool) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	trimmed := strings.TrimSpace(userID)
	if trimmed == "" {
		return errors.New("user ID is required")
	}
	return c.IG.SetUserBlocked(c.opContext(), trimmed, blocked)
}

const igAlphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"

func shortcodeToMediaID(shortcode string) string {
	trimmed := strings.TrimSpace(shortcode)
	if trimmed == "" {
		return ""
	}
	var id uint64
	for i := 0; i < len(trimmed); i++ {
		idx := strings.IndexByte(igAlphabet, trimmed[i])
		if idx < 0 {
			break
		}
		id = id*64 + uint64(idx)
	}
	if id == 0 {
		return ""
	}
	return strconv.FormatUint(id, 10)
}

func extractShortcodeFromInput(raw string) (mediaID, shortcode string) {
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		return "", ""
	}
	if _, err := strconv.ParseUint(trimmed, 10, 64); err == nil {
		return trimmed, ""
	}
	if strings.HasPrefix(trimmed, "http://") || strings.HasPrefix(trimmed, "https://") {
		if u, err := url.Parse(trimmed); err == nil {
			parts := strings.Split(strings.Trim(u.Path, "/"), "/")
			for i := 0; i < len(parts)-1; i++ {
				if parts[i] == "p" || parts[i] == "reel" || parts[i] == "reels" || parts[i] == "tv" {
					shortcode = parts[i+1]
					break
				}
			}
		}
	} else {
		shortcode = strings.Trim(trimmed, "/")
	}
	if shortcode != "" {
		mediaID = shortcodeToMediaID(shortcode)
	}
	return mediaID, shortcode
}

// FetchMedia retrieves Instagram post/reel metadata and CDN download URLs.
func (c *Client) FetchMedia(input string) (*FetchedMediaInfo, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	mediaID, shortcode := extractShortcodeFromInput(input)
	if mediaID == "" {
		return nil, fmt.Errorf("invalid media ID or shortcode: %s", input)
	}
	resp, err := c.IG.FetchMedia(c.opContext(), mediaID, shortcode)
	if err != nil {
		return nil, err
	}
	if resp == nil || len(resp.Items) == 0 || resp.Items[0] == nil {
		return nil, fmt.Errorf("media not found: %s", input)
	}
	item := resp.Items[0]
	var urls []string
	if len(item.CarouselMedia) > 0 {
		for _, sub := range item.CarouselMedia {
			if sub == nil {
				continue
			}
			if len(sub.VideoVersions) > 0 && sub.VideoVersions[0].URL != "" {
				urls = append(urls, sub.VideoVersions[0].URL)
			} else if len(sub.ImageVersions2.Candidates) > 0 && sub.ImageVersions2.Candidates[0].URL != "" {
				urls = append(urls, sub.ImageVersions2.Candidates[0].URL)
			}
		}
	} else {
		if len(item.VideoVersions) > 0 && item.VideoVersions[0].URL != "" {
			urls = append(urls, item.VideoVersions[0].URL)
		} else if len(item.ImageVersions2.Candidates) > 0 && item.ImageVersions2.Candidates[0].URL != "" {
			urls = append(urls, item.ImageVersions2.Candidates[0].URL)
		}
	}
	code := item.Code
	if code == "" {
		code = shortcode
	}
	return &FetchedMediaInfo{
		ID:            item.Pk,
		Shortcode:     code,
		MediaType:     item.MediaType,
		Author:        item.User.Username,
		Caption:       item.Caption.Text,
		LikeCount:     item.LikeCount,
		PlayCount:     item.PlayCount,
		VideoDuration: item.VideoDuration,
		URLs:          urls,
	}, nil
}

// ForwardThreadMessage forwards text or media from one thread to another.
func (c *Client) ForwardThreadMessage(sourceThreadKey, targetThreadKey int64, messageID, customText string) (*SendMessageResult, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	if targetThreadKey == 0 {
		return nil, errors.New("target thread ID is required")
	}
	ctx := c.opContext()
	targetIDs, err := c.resolveIGThreadIDs(ctx, targetThreadKey)
	if err != nil {
		return nil, err
	}
	var sourceLongID *string
	isOwn := false
	textToSend := strings.TrimSpace(customText)
	var mediaURLToSend string

	if sourceThreadKey != 0 {
		if sourceIDs, sErr := c.resolveIGThreadIDs(ctx, sourceThreadKey); sErr == nil && sourceIDs != nil {
			if sourceIDs.LongID != "" {
				sourceLongID = &sourceIDs.LongID
			}
			if messageID != "" && textToSend == "" {
				if tResp, tErr := c.IG.GetThread(ctx, slidetypes.MakeGetThreadInfoRequest(sourceIDs.ShortID)); tErr == nil && tResp != nil && tResp.ThreadInfo.AsIGDirectThread != nil && tResp.ThreadInfo.AsIGDirectThread.SlideMessages != nil {
					for _, edge := range tResp.ThreadInfo.AsIGDirectThread.SlideMessages.Edges {
						m := edge.Node
						if m == nil {
							continue
						}
						if m.ID == messageID || m.MessageID == messageID {
							isOwn = m.SenderFBID == c.OwnID
							textToSend = extractIGMessageText(m)
							atts := extractIGAttachments(m.Content.Content)
							if len(atts) > 0 && atts[0].URL != "" {
								mediaURLToSend = atts[0].URL
							}
							break
						}
					}
				}
			}
		}
	}

	if mediaURLToSend != "" && textToSend == "" {
		return c.SendMediaFromURL(targetThreadKey, mediaURLToSend, "", "", "", false)
	}
	if textToSend == "" {
		return nil, errors.New("could not find message content to forward")
	}

	otid := strconv.FormatInt(methods.GenerateEpochID(), 10)
	req := &slidetypes.SendTextRequest{
		IGThreadIGID:              &targetIDs.ShortID,
		OfflineThreadingID:        otid,
		Text:                      slidetypes.SensitiveString{Value: textToSend},
		ForwardedFromThreadID:     sourceLongID,
		IsForwardedFromOwnMessage: &isOwn,
		SendAttribution:           ptr.Ptr("igd_web_chat_tab:in_thread"),
	}
	resp, err := c.IG.SendMessage(ctx, req)
	if err != nil {
		return nil, err
	}
	sent := resp.GetMessage()
	msgID := sent.ID
	if msgID == "" {
		msgID = sent.MessageID
	}
	if msgID == "" {
		msgID = otid
	}
	tsMs := sent.TimestampMS.UnixMilli()
	if tsMs == 0 {
		tsMs = timeNowMs()
	}
	c.rememberIGMessageThread(msgID, targetIDs.ShortID, targetIDs.LongID)
	return &SendMessageResult{
		MessageID:      msgID,
		TimestampMs:    tsMs,
		DeliveryStatus: DeliveryStatusAcknowledged,
	}, nil
}

// GetWebProfile fetches profile details by `@username` or user/messaging ID.
func (c *Client) GetWebProfile(identifier string) (*WebProfileInfo, error) {
	if c.IG == nil || c.IG.GetHTTP() == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	clean := strings.TrimPrefix(strings.TrimSpace(identifier), "@")
	if clean == "" {
		return nil, errors.New("username or user ID is required")
	}

	var resolvedUsername string
	var resolvedIGID string
	var fallbackInfo *WebProfileInfo

	applyGraphQLProfile := func(u *slidetypes.User, knownMsgID int64) *WebProfileInfo {
		if u == nil {
			return nil
		}
		uid := u.PK
		if uid == "" {
			uid = u.ID
		}
		msgID := u.InteropMessagingUserFBID
		if msgID == 0 && knownMsgID > 0 {
			msgID = knownMsgID
		}
		if msgID == 0 && u.FBIDV2 != "" {
			msgID, _ = strconv.ParseInt(u.FBIDV2, 10, 64)
		}
		extURL := u.ExternalURL
		if extURL == "" && len(u.BioLinks) > 0 {
			extURL = u.BioLinks[0].URL
		}
		hdPic := u.HDProfilePicURLInfo.URL
		if hdPic == "" {
			hdPic = u.ProfilePicURL
		}
		return &WebProfileInfo{
			ID:                uid,
			MessagingID:       msgID,
			Username:          u.Username,
			FullName:          u.FullName,
			Biography:         u.Biography,
			ExternalURL:       extURL,
			ProfilePicURL:     u.ProfilePicURL,
			ProfilePicURLHD:   hdPic,
			IsPrivate:         u.IsPrivate,
			IsVerified:        u.IsVerified,
			IsBusinessAccount: u.IsBusiness || u.IsProfessional,
			FollowerCount:     u.FollowerCount,
			FollowingCount:    u.FollowingCount,
			PostCount:         u.MediaCount,
		}
	}

	if numericID, err := strconv.ParseInt(clean, 10, 64); err == nil && numericID > 0 {
		if dmResp, dmErr := c.IG.GetUserForNewDM(ctx, numericID); dmErr == nil && dmResp != nil && dmResp.Data != nil {
			u := dmResp.Data
			resolvedUsername = u.Username
			uid := u.PK
			if uid == "" {
				uid = u.ID
			}
			resolvedIGID = uid
			msgID := u.InteropMessagingUserFBID
			if msgID == 0 {
				msgID = numericID
			}
			fallbackInfo = &WebProfileInfo{
				ID:            uid,
				MessagingID:   msgID,
				Username:      u.Username,
				FullName:      u.FullName,
				ProfilePicURL: u.ProfilePicURL,
				IsVerified:    u.IsVerified,
			}
		} else {
			resolvedIGID = clean
		}
		if resolvedIGID != "" {
			if profResp, profErr := c.IG.GetProfile(ctx, resolvedIGID); profErr == nil && profResp != nil && profResp.User != nil {
				knownMsgID := int64(0)
				if fallbackInfo != nil {
					knownMsgID = fallbackInfo.MessagingID
				}
				fallbackInfo = applyGraphQLProfile(profResp.User, knownMsgID)
				if fallbackInfo != nil && fallbackInfo.Username != "" {
					resolvedUsername = fallbackInfo.Username
				}
			}
		}
	} else {
		resolvedUsername = clean
	}

	if resolvedUsername != "" {
		h := c.IG.GetHTTP().BuildHeaders(true, false)
		h.Set("x-requested-with", "XMLHttpRequest")
		h.Set("referer", fmt.Sprintf("%s/%s/", c.IG.GetEndpoint("base_url"), resolvedUsername))
		h.Set("sec-fetch-dest", "empty")
		h.Set("sec-fetch-mode", "cors")
		h.Set("sec-fetch-site", "same-origin")
		reqURL := c.IG.GetEndpoint("web_profile_info") + "username=" + url.QueryEscape(resolvedUsername)
		_, respBody, err := c.IG.GetHTTP().MakeRequest(ctx, reqURL, http.MethodGet, h, nil, types.NONE)
		if err == nil && len(respBody) > 0 {
			var webProf responses.ProfileInfoResponse
			if jsonErr := json.Unmarshal(respBody, &webProf); jsonErr == nil && webProf.Data.User.Username != "" {
				u := webProf.Data.User
				var msgID int64
				if u.EimuID != "" {
					msgID, _ = strconv.ParseInt(u.EimuID, 10, 64)
				}
				if msgID == 0 && u.Fbid != "" {
					msgID, _ = strconv.ParseInt(u.Fbid, 10, 64)
				}
				if msgID == 0 && fallbackInfo != nil {
					msgID = fallbackInfo.MessagingID
				}
				extURL, _ := u.ExternalURL.(string)
				var recentPosts []*WebProfilePost
				for _, edge := range u.EdgeOwnerToTimelineMedia.Edges {
					node := edge.Node
					if node.Shortcode == "" && node.ID == "" {
						continue
					}
					caption := ""
					if len(node.EdgeMediaToCaption.Edges) > 0 {
						caption = node.EdgeMediaToCaption.Edges[0].Node.Text
					}
					postURL := ""
					if node.Shortcode != "" {
						postURL = fmt.Sprintf("https://www.instagram.com/p/%s/", node.Shortcode)
					}
					recentPosts = append(recentPosts, &WebProfilePost{
						ID:           node.ID,
						Shortcode:    node.Shortcode,
						URL:          postURL,
						DisplayURL:   node.DisplayURL,
						Caption:      caption,
						IsVideo:      node.IsVideo,
						LikeCount:    node.EdgeLikedBy.Count,
						CommentCount: node.EdgeMediaToComment.Count,
						TakenAt:      node.TakenAtTimestamp,
					})
					if len(recentPosts) >= 5 {
						break
					}
				}
				return &WebProfileInfo{
					ID:                u.ID,
					MessagingID:       msgID,
					Username:          u.Username,
					FullName:          u.FullName,
					Biography:         u.Biography,
					ExternalURL:       extURL,
					ProfilePicURL:     u.ProfilePicURL,
					ProfilePicURLHD:   u.ProfilePicURLHd,
					IsPrivate:         u.IsPrivate,
					IsVerified:        u.IsVerified,
					IsBusinessAccount: u.IsBusinessAccount,
					FollowerCount:     u.EdgeFollowedBy.Count,
					FollowingCount:    u.EdgeFollow.Count,
					PostCount:         u.EdgeOwnerToTimelineMedia.Count,
					RecentPosts:       recentPosts,
				}, nil
			}
		}
	}

	if fallbackInfo != nil {
		return fallbackInfo, nil
	}

	if searchResp, sErr := c.IG.SearchUsers(ctx, clean); sErr == nil && searchResp != nil {
		for _, r := range searchResp.Data.Results {
			if r == nil {
				continue
			}
			pk := r.PK
			if pk == "" {
				pk = r.ID
			}
			if strings.EqualFold(r.Username, clean) || pk == clean || strconv.FormatInt(r.InteropMessagingUserFBID, 10) == clean {
				if pk != "" {
					if profResp, profErr := c.IG.GetProfile(ctx, pk); profErr == nil && profResp != nil && profResp.User != nil {
						if fullProf := applyGraphQLProfile(profResp.User, r.InteropMessagingUserFBID); fullProf != nil {
							return fullProf, nil
						}
					}
				}
				return &WebProfileInfo{
					ID:            pk,
					MessagingID:   r.InteropMessagingUserFBID,
					Username:      r.Username,
					FullName:      r.FullName,
					ProfilePicURL: r.ProfilePicURL,
					IsVerified:    r.IsVerified,
				}, nil
			}
		}
	}
	return nil, fmt.Errorf("profile not found: %s", identifier)
}

// FetchStories fetches active 24h stories or highlights for an Instagram user.
func (c *Client) FetchStories(identifier string) (*FetchedStoriesResult, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	clean := strings.TrimPrefix(strings.TrimSpace(identifier), "@")
	if clean == "" {
		return nil, errors.New("username or user ID is required")
	}

	reelID := clean
	username := ""
	fullName := ""

	if !strings.HasPrefix(clean, "highlight:") {
		if prof, err := c.GetWebProfile(clean); err == nil && prof != nil && prof.ID != "" {
			reelID = prof.ID
			username = prof.Username
			fullName = prof.FullName
		}
	}

	resp, err := c.IG.FetchReel(ctx, []string{reelID}, "")
	if err != nil {
		return nil, err
	}
	var items []*StoryItemInfo
	if resp != nil {
		reels := resp.ReelsMedia
		if len(reels) == 0 && len(resp.Reels) > 0 {
			for _, r := range resp.Reels {
				reels = append(reels, r)
			}
		}
		for _, reel := range reels {
			if reel.User != nil {
				if username == "" {
					username = reel.User.Username
				}
				if fullName == "" {
					fullName = reel.User.FullName
				}
			}
			for _, item := range reel.Items {
				if item == nil {
					continue
				}
				mediaURL := ""
				previewURL := ""
				if len(item.ImageVersions2.Candidates) > 0 {
					previewURL = item.ImageVersions2.Candidates[0].URL
				}
				if len(item.VideoVersions) > 0 && item.VideoVersions[0].URL != "" {
					mediaURL = item.VideoVersions[0].URL
				} else {
					mediaURL = previewURL
				}
				if mediaURL == "" {
					continue
				}
				items = append(items, &StoryItemInfo{
					ID:            item.Pk,
					Shortcode:     item.Code,
					MediaType:     item.MediaType,
					URL:           mediaURL,
					PreviewURL:    previewURL,
					TakenAt:       item.TakenAt,
					ExpiringAt:    item.ExpiringAt,
					VideoDuration: item.VideoDuration,
					Caption:       item.Caption.Text,
				})
			}
		}
	}
	return &FetchedStoriesResult{
		UserID:   reelID,
		Username: username,
		FullName: fullName,
		Count:    len(items),
		Items:    items,
	}, nil
}

// PaginateInbox fetches a page of Instagram threads by cursor and folder (`INBOX`/`PENDING`).
func (c *Client) PaginateInbox(cursor, folder string) (*PaginatedInboxResult, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	targetFolder := strings.TrimSpace(folder)
	if targetFolder == "" {
		targetFolder = "INBOX"
	}
	if strings.TrimSpace(cursor) == "" && strings.EqualFold(targetFolder, "INBOX") {
		mbResp, err := c.IG.GetMailbox(ctx)
		if err != nil {
			return nil, err
		}
		var threads []*Thread
		nextCur := ""
		hasNext := false
		if mb := mbResp.GetMailbox(); mb != nil {
			for _, edge := range mb.ThreadsByFolder.Edges {
				if t := c.cacheIGThreadInfo(edge.Node.AsIGDirectThread); t != nil {
					threads = append(threads, t)
				}
			}
			nextCur = mb.ThreadsByFolder.PageInfo.EndCursor
			hasNext = mb.ThreadsByFolder.PageInfo.HasNextPage
		}
		return &PaginatedInboxResult{
			Threads:     threads,
			NextCursor:  nextCur,
			HasNextPage: hasNext,
		}, nil
	}
	pResp, err := c.IG.PaginateMailbox(ctx, slidetypes.MakePaginateMailboxRequest(c.OwnID, cursor, targetFolder, nil))
	if err != nil {
		return nil, err
	}
	var threads []*Thread
	nextCur := ""
	hasNext := false
	if pResp != nil && pResp.Mailbox != nil {
		for _, edge := range pResp.Mailbox.ThreadsByFolder.Edges {
			if t := c.cacheIGThreadInfo(edge.Node.AsIGDirectThread); t != nil {
				threads = append(threads, t)
			}
		}
		nextCur = pResp.Mailbox.ThreadsByFolder.PageInfo.EndCursor
		hasNext = pResp.Mailbox.ThreadsByFolder.PageInfo.HasNextPage
	}
	return &PaginatedInboxResult{
		Threads:     threads,
		NextCursor:  nextCur,
		HasNextPage: hasNext,
	}, nil
}

// PaginateMessages fetches older messages inside an Instagram Direct thread.
func (c *Client) PaginateMessages(threadKey int64, cursor string, limit int) (*PaginatedMessagesResult, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	ids, err := c.resolveIGThreadIDs(ctx, threadKey)
	if err != nil {
		return nil, err
	}
	if limit <= 0 || limit > 50 {
		limit = 20
	}
	var curPtr *string
	if trimmed := strings.TrimSpace(cursor); trimmed != "" {
		curPtr = &trimmed
	}
	pResp, err := c.IG.PaginateMessages(ctx, &slidetypes.PaginateMessagesRequest{
		AfterCursor:             curPtr,
		FirstN:                  limit,
		ThreadID:                ids.ShortID,
		InitialMessagePageCount: limit,
	})
	if err != nil {
		return nil, err
	}
	var messages []*Message
	nextCur := ""
	hasNext := false
	if pResp != nil && pResp.ThreadInfo.AsIGDirectThread != nil && pResp.ThreadInfo.AsIGDirectThread.Messages != nil {
		sm := pResp.ThreadInfo.AsIGDirectThread.Messages
		for _, edge := range sm.Edges {
			msg := edge.Node
			if msg == nil {
				continue
			}
			msgID := msg.ID
			if msgID == "" {
				msgID = msg.MessageID
			}
			messages = append(messages, &Message{
				ID:          msgID,
				ThreadID:    threadKey,
				SenderID:    msg.SenderFBID,
				Text:        extractIGMessageText(msg),
				TimestampMs: msg.TimestampMS.UnixMilli(),
				Attachments: extractIGAttachments(msg.Content.Content),
			})
		}
		nextCur = sm.PageInfo.EndCursor
		if nextCur == "" {
			nextCur = sm.PageInfo.StartCursor
		}
		hasNext = sm.PageInfo.HasNextPage || sm.PageInfo.HasPreviousPage
	}
	return &PaginatedMessagesResult{
		ThreadID:    threadKey,
		Messages:    messages,
		NextCursor:  nextCur,
		HasNextPage: hasNext,
	}, nil
}

// GetUnreadCount fetches the total unread Instagram Direct thread count.
func (c *Client) GetUnreadCount() (map[string]any, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	count, err := c.IG.GetUnreadThreadCount(c.opContext())
	if err != nil {
		return nil, err
	}
	return map[string]any{"unreadCount": count}, nil
}
