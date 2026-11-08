package bridge

import (
	"context"
	"errors"
	"fmt"
	"reflect"
	"strings"
	"time"

	"go.mau.fi/mautrix-meta/pkg/instameow"
	"go.mau.fi/mautrix-meta/pkg/instameow/slidetypes"
	"go.mau.fi/mautrix-meta/pkg/messagix/dgw"
)

var timeNowMs = func() int64 {
	return time.Now().UnixMilli()
}

// EventType identifies normalized events emitted over the stdout RPC stream.
type EventType string

const (
	EventTypeReady         EventType = "ready"
	EventTypeReconnected   EventType = "reconnected"
	EventTypeDisconnected  EventType = "disconnected"
	EventTypeError         EventType = "error"
	EventTypeRaw           EventType = "raw"
	EventTypeMessage       EventType = "message"
	EventTypeMessageEdit   EventType = "messageEdit"
	EventTypeMessageUnsend EventType = "messageUnsend"
	EventTypeReaction      EventType = "reaction"
	EventTypeTyping        EventType = "typing"
	EventTypeReadReceipt   EventType = "readReceipt"
	EventTypeThreadUpdate  EventType = "threadUpdate"
)

// Event represents an outbound event emitted by the Instagram bridge.
type Event struct {
	Type      EventType `json:"type"`
	Data      any       `json:"data"`
	Timestamp int64     `json:"timestamp"`
}

// UserInfo holds authenticated Instagram user metadata.
type UserInfo struct {
	ID       int64  `json:"id"`
	Name     string `json:"name"`
	Username string `json:"username"`
}

// InitialData holds initial Instagram Direct threads retrieved on connect.
type InitialData struct {
	Threads  []*Thread  `json:"threads"`
	Messages []*Message `json:"messages"`
}

// Thread represents an Instagram Direct conversation thread.
type Thread struct {
	ID                      int64  `json:"id"`
	Type                    int    `json:"type"`
	Name                    string `json:"name"`
	LastActivityTimestampMs int64  `json:"lastActivityTimestampMs"`
	Snippet                 string `json:"snippet"`
}

// Attachment represents an Instagram Direct attachment (media, sticker, link, audio).
type Attachment struct {
	Type        string  `json:"type"`
	URL         string  `json:"url,omitempty"`
	FileName    string  `json:"fileName,omitempty"`
	MimeType    string  `json:"mimeType,omitempty"`
	FileSize    int64   `json:"fileSize,omitempty"`
	Width       int     `json:"width,omitempty"`
	Height      int     `json:"height,omitempty"`
	Duration    int     `json:"duration,omitempty"`
	StickerID   int64   `json:"stickerId,omitempty"`
	Latitude    float64 `json:"latitude,omitempty"`
	Longitude   float64 `json:"longitude,omitempty"`
	PreviewURL  string  `json:"previewUrl,omitempty"`
	Description string  `json:"description,omitempty"`
	SourceText  string  `json:"sourceText,omitempty"`
}

// ReplyTo represents the quoted message context on a reply.
type ReplyTo struct {
	MessageID string `json:"messageId"`
	SenderID  int64  `json:"senderId,omitempty"`
	Text      string `json:"text,omitempty"`
}

// Mention represents a UTF-16 offset mention inside a message.
type Mention struct {
	UserID int64  `json:"userId"`
	Offset int    `json:"offset"`
	Length int    `json:"length"`
	Type   string `json:"type,omitempty"`
}

// Message represents a normalized Instagram Direct message.
type Message struct {
	ID          string        `json:"id"`
	ThreadID    int64         `json:"threadId"`
	ThreadName  string        `json:"threadName,omitempty"`
	ThreadType  int           `json:"threadType,omitempty"`
	SenderID    int64         `json:"senderId"`
	Text        string        `json:"text"`
	TimestampMs int64         `json:"timestampMs"`
	Attachments []*Attachment `json:"attachments,omitempty"`
	ReplyTo     *ReplyTo      `json:"replyTo,omitempty"`
	Mentions    []*Mention    `json:"mentions,omitempty"`
	IsAdminMsg  bool          `json:"isAdminMsg,omitempty"`
}

// MessageEditEvent represents a Slide message edit delta.
type MessageEditEvent struct {
	MessageID   string `json:"messageId"`
	ThreadID    int64  `json:"threadId"`
	NewText     string `json:"newText"`
	EditCount   int64  `json:"editCount"`
	TimestampMs int64  `json:"timestampMs"`
}

// ReadReceiptEvent represents a read watermark update in a thread.
type ReadReceiptEvent struct {
	ThreadID                 int64 `json:"threadId"`
	ReaderID                 int64 `json:"readerId"`
	ReadWatermarkTimestampMs int64 `json:"readWatermarkTimestampMs"`
	TimestampMs              int64 `json:"timestampMs,omitempty"`
}

// ReactionEvent represents a reaction create/delete delta.
type ReactionEvent struct {
	MessageID   string `json:"messageId"`
	ThreadID    int64  `json:"threadId"`
	ActorID     int64  `json:"actorId"`
	Reaction    string `json:"reaction"`
	TimestampMs int64  `json:"timestampMs"`
}

// TypingEvent represents a typing activity indicator notification.
type TypingEvent struct {
	ThreadID int64 `json:"threadId"`
	SenderID int64 `json:"senderId"`
	IsTyping bool  `json:"isTyping"`
}

// ErrorEvent represents a sanitized bridge error notification.
type ErrorEvent struct {
	Message string `json:"message"`
	Code    int    `json:"code,omitempty"`
}

// RawEventSource identifies the upstream Instagram stream for raw events.
type RawEventSource string

const RawEventSourceInstameow RawEventSource = "instameow"

// RawEvent carries raw unparsed instameow events for debugging or tracing.
type RawEvent struct {
	From RawEventSource `json:"from"`
	Type string         `json:"type"`
	Data any            `json:"data"`
}

func getEventTypeName(evt any) string {
	if evt == nil {
		return "nil"
	}
	t := reflect.TypeOf(evt)
	if t.Kind() == reflect.Ptr {
		return t.Elem().Name()
	}
	return t.Name()
}

func (c *Client) claimMessageID(messageID string) bool {
	if messageID == "" {
		return true
	}
	now := timeNowMs()
	c.recentMessagesMu.Lock()
	defer c.recentMessagesMu.Unlock()
	if c.recentMessages == nil {
		c.recentMessages = make(map[string]int64)
	}
	if now >= c.recentMessageSweep {
		for existingID, emittedAt := range c.recentMessages {
			if now-emittedAt > recentMessageTTLms {
				delete(c.recentMessages, existingID)
			}
		}
		c.recentMessageSweep = now + recentMessageSweepMs
	}
	if _, exists := c.recentMessages[messageID]; exists {
		return false
	}
	if len(c.recentMessages) >= maxRecentMessages {
		var oldestID string
		oldestTs := now
		for existingID, emittedAt := range c.recentMessages {
			if oldestID == "" || emittedAt < oldestTs {
				oldestID = existingID
				oldestTs = emittedAt
			}
		}
		if oldestID != "" {
			delete(c.recentMessages, oldestID)
		}
	}
	c.recentMessages[messageID] = now
	return true
}

func (c *Client) handleIGEvent(ctx context.Context, rawEvt slidetypes.ClientEvent) error {
	c.emitEvent(EventTypeRaw, &RawEvent{
		From: RawEventSourceInstameow,
		Type: getEventTypeName(rawEvt),
		Data: rawEvt,
	})

	switch evt := rawEvt.(type) {
	case *slidetypes.Connected:
		wasConnected := c.connected.Swap(true)
		wasEver := c.everConnected.Swap(true)
		c.clearTransportFailure()
		if !wasConnected && wasEver {
			c.emitEvent(EventTypeReconnected, nil)
		} else {
			c.emitEvent(EventTypeReady, map[string]any{
				"isNewSession": false,
			})
		}
		return nil

	case *slidetypes.Disconnected:
		c.connected.Store(false)
		if dgw.IsUnauthorized(evt.Error) || errors.Is(evt.Error, instameow.ErrUserIDMissing) {
			c.emitConnectionFailure(permanentConnectionFailure(evt.Error))
			return fmt.Errorf("instagram dgw unauthorized: %w", evt.Error)
		}
		if evt.FailureCount > 5 && errors.Is(evt.Error, instameow.ErrMainStreamClosed) {
			c.emitConnectionFailure(permanentConnectionFailure(evt.Error))
			return fmt.Errorf("instagram main stream closed repeatedly: %w", evt.Error)
		}
		c.emitConnectionFailure(transientConnectionFailure(evt.Error))
		return nil

	case *slidetypes.AuthError:
		c.connected.Store(false)
		c.emitConnectionFailure(permanentConnectionFailure(evt.Error))
		return nil

	case *slidetypes.SeqIDUpdate, *slidetypes.ReconnectionStateUpdate, *slidetypes.ResnapshotRequired:
		return nil

	case *slidetypes.TypingNotification:
		threadKey := c.resolveIGThreadKey(evt.ThreadID)
		c.emitEvent(EventTypeTyping, &TypingEvent{
			ThreadID: threadKey,
			SenderID: evt.SenderID,
			IsTyping: evt.ActivityStatus != 0,
		})
		return nil

	case *slidetypes.Delta:
		c.handleIGDelta(ctx, evt)
		return nil

	default:
		return nil
	}
}

func (c *Client) resolveDeltaThreadKey(threadIGID, messageID string) int64 {
	if threadIGID != "" {
		if key := c.resolveIGThreadKey(threadIGID); key != 0 {
			return key
		}
	}
	if messageID != "" {
		if ids := c.lookupIGMessageThread(messageID); ids != nil {
			if ids.ShortID != "" {
				return c.resolveIGThreadKey(ids.ShortID)
			}
			if ids.LongID != "" {
				return c.resolveIGThreadKey(ids.LongID)
			}
		}
	}
	return 0
}

func (c *Client) handleIGDelta(_ context.Context, d *slidetypes.Delta) {
	if d == nil || d.Data == nil {
		return
	}
	switch evt := d.Data.(type) {
	case *slidetypes.NewMessageEvent:
		if evt.Message == nil {
			return
		}
		threadIGID := d.ThreadIGID
		if threadIGID == "" {
			threadIGID = evt.Message.ThreadFBID
		}
		c.emitIGSlideMessage(threadIGID, evt.Message, false)

	case *slidetypes.AdminMessageEvent:
		if evt.Message == nil {
			return
		}
		threadIGID := d.ThreadIGID
		if threadIGID == "" {
			threadIGID = evt.Message.ThreadFBID
		}
		c.emitIGSlideMessage(threadIGID, evt.Message, true)

	case *slidetypes.EditMessageEvent:
		threadKey := c.resolveDeltaThreadKey(d.ThreadIGID, evt.MessageID)
		c.emitEvent(EventTypeMessageEdit, &MessageEditEvent{
			MessageID:   evt.MessageID,
			ThreadID:    threadKey,
			NewText:     evt.TextBody,
			TimestampMs: evt.SlideEditHistoryEntry.TimestampMS.UnixMilli(),
		})

	case *slidetypes.DeleteMessageEvent:
		threadKey := c.resolveDeltaThreadKey(d.ThreadIGID, evt.MessageID)
		c.emitEvent(EventTypeMessageUnsend, map[string]any{
			"messageId": evt.MessageID,
			"threadId":  threadKey,
		})

	case *slidetypes.CreateReactionEvent:
		threadKey := c.resolveDeltaThreadKey(d.ThreadIGID, evt.MessageID)
		c.emitEvent(EventTypeReaction, &ReactionEvent{
			MessageID:   evt.MessageID,
			ThreadID:    threadKey,
			ActorID:     evt.Reaction.SenderFBID,
			Reaction:    evt.Reaction.Reaction,
			TimestampMs: evt.Reaction.ReactionTimestampMS.UnixMilli(),
		})

	case *slidetypes.DeleteReactionEvent:
		threadKey := c.resolveDeltaThreadKey(d.ThreadIGID, evt.MessageID)
		c.emitEvent(EventTypeReaction, &ReactionEvent{
			MessageID: evt.MessageID,
			ThreadID:  threadKey,
			ActorID:   evt.Reaction.SenderFBID,
			Reaction:  "",
		})

	case *slidetypes.ReadReceiptEvent:
		threadKey := c.resolveIGThreadKey(d.ThreadIGID)
		c.emitEvent(EventTypeReadReceipt, &ReadReceiptEvent{
			ThreadID:                 threadKey,
			ReaderID:                 evt.ReadReceipt.ParticipantFBID,
			ReadWatermarkTimestampMs: evt.ReadReceipt.WatermarkTimestampMS.UnixMilli(),
		})

	case *slidetypes.MarkReadEvent:
		threadKey := c.resolveIGThreadKey(d.ThreadIGID)
		c.emitEvent(EventTypeReadReceipt, &ReadReceiptEvent{
			ThreadID:                 threadKey,
			ReaderID:                 c.OwnID,
			ReadWatermarkTimestampMs: evt.ReadTimestampMS.UnixMilli(),
		})

	case *slidetypes.UpdateThreadNameEvent:
		threadKey := c.resolveIGThreadKey(d.ThreadIGID)
		if threadKey != 0 && evt.ThreadName != "" {
			c.mu.Lock()
			if existing, ok := c.threadCache[threadKey]; ok && existing != nil {
				existing.Name = evt.ThreadName
			}
			c.mu.Unlock()
		}
		if evt.Message != nil {
			c.emitIGSlideMessage(d.ThreadIGID, evt.Message, true)
		}

	case *slidetypes.UpdateThreadImageEvent:
		if evt.Message != nil {
			c.emitIGSlideMessage(d.ThreadIGID, evt.Message, true)
		}

	case *slidetypes.ParticipantJoinEvent:
		if evt.Message != nil {
			c.emitIGSlideMessage(d.ThreadIGID, evt.Message, true)
		}

	case *slidetypes.ParticipantLeaveEvent:
		if evt.Message != nil {
			c.emitIGSlideMessage(d.ThreadIGID, evt.Message, true)
		}

	case *slidetypes.MarkUnreadEvent:
		threadKey := c.resolveIGThreadKey(d.ThreadIGID)
		c.emitEvent(EventTypeThreadUpdate, map[string]any{
			"action":         "markUnread",
			"threadId":       threadKey,
			"markedAsUnread": evt.MarkedAsUnread,
		})

	case *slidetypes.DeleteThreadEvent:
		threadKey := c.resolveIGThreadKey(d.ThreadIGID)
		if threadKey != 0 {
			c.mu.Lock()
			delete(c.threadCache, threadKey)
			c.mu.Unlock()
		}
		c.emitEvent(EventTypeThreadUpdate, map[string]any{
			"action":   "deleteThread",
			"threadId": threadKey,
		})

	case *slidetypes.UpdateThreadFolderEvent:
		threadKey := c.resolveIGThreadKey(d.ThreadIGID)
		c.emitEvent(EventTypeThreadUpdate, map[string]any{
			"action":        "updateFolder",
			"threadId":      threadKey,
			"folder":        evt.Folder,
			"igInboxFolder": evt.IGInboxFolder,
		})

	case *slidetypes.AdminChangeEvent:
		threadKey := c.resolveIGThreadKey(d.ThreadIGID)
		c.emitEvent(EventTypeThreadUpdate, map[string]any{
			"action":     "adminChange",
			"threadId":   threadKey,
			"adminIgids": evt.AdminIGIDs,
		})

	case *slidetypes.MuteThreadEvent:
		threadKey := c.resolveIGThreadKey(d.ThreadIGID)
		c.emitEvent(EventTypeThreadUpdate, map[string]any{
			"action":     "muteThread",
			"threadId":   threadKey,
			"isMutedNow": evt.IsMutedNow,
		})

	case *slidetypes.PinThreadEvent:
		threadKey := c.resolveIGThreadKey(d.ThreadIGID)
		c.emitEvent(EventTypeThreadUpdate, map[string]any{
			"action":   "pinThread",
			"threadId": threadKey,
			"isPinned": evt.IsPinned,
		})

	case *slidetypes.PinMessageEvent:
		threadKey := c.resolveIGThreadKey(d.ThreadIGID)
		c.emitEvent(EventTypeThreadUpdate, map[string]any{
			"action":           "pinMessage",
			"threadId":         threadKey,
			"pinnedMessages":   evt.PinnedMessages,
			"unpinnedMessages": evt.UnpinnedMessages,
		})
	}
}

func extractIGMessageText(msg *slidetypes.Message) string {
	if msg == nil {
		return ""
	}
	if msg.TextBody != "" {
		return msg.TextBody
	}
	switch content := msg.Content.Content.(type) {
	case *slidetypes.MessageContentText:
		if content != nil {
			return content.TextBody
		}
	case *slidetypes.MessageContentXMA:
		if content != nil {
			return content.XMATextBody
		}
	case *slidetypes.MessageContentAdminText:
		if content != nil && len(content.TextFragments) > 0 {
			var sb strings.Builder
			for _, frag := range content.TextFragments {
				sb.WriteString(frag.Plaintext)
			}
			return sb.String()
		}
	case *slidetypes.MessageContentAIRichResponse:
		if content != nil {
			return content.UnifiedResponse
		}
	case *slidetypes.MessageContentAISearchResponse:
		if content != nil {
			return content.MessageTextBody
		}
	case *slidetypes.MessageContentMusicSticker:
		if content != nil && content.AudioTrack.Title != "" {
			return fmt.Sprintf("🎵 %s - %s", content.AudioTrack.Title, content.AudioTrack.DisplayArtist)
		}
	}
	return ""
}

func (c *Client) emitIGSlideMessage(threadIGID string, msg *slidetypes.Message, isAdmin bool) {
	if msg == nil {
		return
	}
	msgID := msg.ID
	if msgID == "" {
		msgID = msg.MessageID
	}
	if msgID != "" && !c.claimMessageID(msgID) {
		return
	}

	threadKey := c.resolveIGThreadKey(threadIGID)
	if threadKey == 0 && msg.SenderFBID != 0 && msg.SenderFBID != c.OwnID {
		threadKey = msg.SenderFBID
	}

	c.mu.RLock()
	var ids *instameow.ThreadIGIDs
	if c.igThreadIDMap != nil {
		ids = c.igThreadIDMap[threadKey]
	}
	c.mu.RUnlock()
	shortID := threadIGID
	longID := threadIGID
	if ids != nil {
		if ids.ShortID != "" {
			shortID = ids.ShortID
		}
		if ids.LongID != "" {
			longID = ids.LongID
		}
	}
	c.rememberIGMessageThread(msgID, shortID, longID)

	text := extractIGMessageText(msg)

	var replyTo *ReplyTo
	if msg.RepliedToMessageID != "" {
		replyTo = &ReplyTo{
			MessageID: msg.RepliedToMessageID,
		}
		if msg.RepliedToMessage != nil {
			replyTo.SenderID = msg.RepliedToMessage.SenderFBID
			replyTo.Text = msg.RepliedToMessage.TextBody
		}
	}

	var mentions []*Mention
	for _, m := range msg.Mentions {
		if m == nil {
			continue
		}
		mentions = append(mentions, &Mention{
			UserID: m.UserFBID,
			Offset: m.Offset,
			Length: m.Length,
			Type:   string(m.ProfileRangeType),
		})
	}

	tsMs := msg.TimestampMS.UnixMilli()
	if tsMs == 0 {
		tsMs = timeNowMs()
	}

	attachments := extractIGAttachments(msg.Content.Content)
	threadName, threadType := c.threadMeta(threadKey)

	c.emitEvent(EventTypeMessage, &Message{
		ID:          msgID,
		ThreadID:    threadKey,
		ThreadName:  threadName,
		ThreadType:  threadType,
		SenderID:    msg.SenderFBID,
		Text:        text,
		TimestampMs: tsMs,
		Attachments: attachments,
		ReplyTo:     replyTo,
		Mentions:    mentions,
		IsAdminMsg:  isAdmin,
	})
}

func convertIGMediaAttachment(att *slidetypes.Attachment, defaultType string) *Attachment {
	if att == nil {
		return nil
	}
	attType := defaultType
	if attType == "" {
		if att.DashManifest != "" || strings.Contains(strings.ToLower(att.Typename), "video") {
			attType = "video"
		} else {
			attType = "image"
		}
	}
	mediaURL := att.AttachmentCDNURL
	if mediaURL == "" {
		mediaURL = att.AttachmentCDNFallbackURL
	}
	previewURL := att.PreviewCDNURL
	if previewURL == "" {
		previewURL = att.PreviewCDNFallbackURL
	}
	if mediaURL == "" {
		mediaURL = previewURL
	}
	return &Attachment{
		Type:       attType,
		URL:        mediaURL,
		PreviewURL: previewURL,
		Width:      att.PreviewWidth,
		Height:     att.PreviewHeight,
	}
}

func extractIGAttachments(content slidetypes.MessageContent) []*Attachment {
	if content == nil {
		return nil
	}
	var out []*Attachment
	switch c := content.(type) {
	case *slidetypes.MessageContentImage:
		for _, a := range c.Attachments {
			if converted := convertIGMediaAttachment(a, "image"); converted != nil {
				out = append(out, converted)
			}
		}
	case *slidetypes.MessageContentVideo:
		for _, a := range c.Videos {
			if converted := convertIGMediaAttachment(a, "video"); converted != nil {
				out = append(out, converted)
			}
		}
	case *slidetypes.MessageContentMultiMedia:
		for _, a := range c.Attachments {
			if converted := convertIGMediaAttachment(a, ""); converted != nil {
				out = append(out, converted)
			}
		}
	case *slidetypes.MessageContentRavenImage:
		if converted := convertIGMediaAttachment(c.Attachment, "image"); converted != nil {
			out = append(out, converted)
		}
	case *slidetypes.MessageContentRavenVideo:
		if converted := convertIGMediaAttachment(c.Attachment, "video"); converted != nil {
			out = append(out, converted)
		}
	case *slidetypes.MessageContentAudio:
		for _, a := range c.AudioAttachments {
			if a == nil {
				continue
			}
			out = append(out, &Attachment{
				Type:     "audio",
				URL:      a.AttachmentCDNURL,
				Duration: a.PlayableDurationMS / 1000,
			})
		}
	case *slidetypes.MessageContentAnimatedMedia:
		for _, a := range c.AnimatedMedia {
			if a == nil {
				continue
			}
			attType := "gif"
			if a.IsSticker {
				attType = "sticker"
			}
			mediaURL := a.AttachmentMP4URL
			if mediaURL == "" {
				mediaURL = a.AttachmentWebpURL
			}
			if mediaURL == "" {
				mediaURL = a.PreviewCDNURL
			}
			out = append(out, &Attachment{
				Type:        attType,
				URL:         mediaURL,
				PreviewURL:  a.PreviewCDNURL,
				Width:       a.PreviewWidth,
				Height:      a.PreviewHeight,
				Description: a.AltText,
			})
		}
	case *slidetypes.MessageContentSticker:
		if c.PreviewURL != "" {
			out = append(out, &Attachment{
				Type:        "sticker",
				URL:         c.PreviewURL,
				PreviewURL:  c.PreviewURL,
				Width:       c.PreviewWidth,
				Height:      c.PreviewHeight,
				Description: c.AltText,
			})
		}
	case *slidetypes.MessageContentXMA:
		if c.XMA != nil {
			previewURL := ""
			width, height := 0, 0
			if c.XMA.PreviewImage != nil {
				previewURL = c.XMA.PreviewImage.URL
				width = c.XMA.PreviewImage.Width
				height = c.XMA.PreviewImage.Height
			} else if c.XMA.XMAPreviewImage != nil {
				previewURL = c.XMA.XMAPreviewImage.URL
				width = c.XMA.XMAPreviewImage.Width
				height = c.XMA.XMAPreviewImage.Height
			}
			title := c.XMA.TitleText
			if title == "" {
				title = c.XMA.XMATitle
			}
			if c.XMA.TargetURL != "" || previewURL != "" {
				out = append(out, &Attachment{
					Type:        "link",
					URL:         c.XMA.TargetURL,
					PreviewURL:  previewURL,
					FileName:    title,
					Description: c.XMA.SubtitleText,
					SourceText:  c.XMA.HeaderTitleText,
					Width:       width,
					Height:      height,
				})
			}
		}
	case *slidetypes.MessageContentMusicSticker:
		if c != nil {
			mediaURL := c.AudioTrack.Web30SPreviewDownloadURL
			if mediaURL == "" {
				mediaURL = c.AttributionLink
			}
			if mediaURL == "" {
				mediaURL = c.PreviewURL
			}
			if mediaURL != "" {
				out = append(out, &Attachment{
					Type:        "music_sticker",
					URL:         mediaURL,
					PreviewURL:  c.PreviewURL,
					FileName:    c.AudioTrack.Title,
					Description: c.AudioTrack.DisplayArtist,
				})
			}
		}
	case *slidetypes.MessageContentAISearchResponse:
		if c != nil {
			for _, src := range c.SearchSources {
				if src.SourceURL != "" {
					out = append(out, &Attachment{
						Type:        "link",
						URL:         src.SourceURL,
						FileName:    src.SourceTitle,
						Description: src.SourceSubtitle,
					})
				}
			}
		}
	case *slidetypes.MessageContentAdminText:
		if c != nil {
			for _, frag := range c.TextFragments {
				if frag.LinkFragment != nil && frag.LinkFragment.URI != "" {
					out = append(out, &Attachment{
						Type:        "link",
						URL:         frag.LinkFragment.URI,
						Description: frag.Plaintext,
					})
				}
			}
		}
	}
	return out
}

