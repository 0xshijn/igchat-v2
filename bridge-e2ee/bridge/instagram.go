package bridge

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"path"
	"strconv"
	"strings"
	"time"

	"go.mau.fi/util/jsontime"
	"go.mau.fi/util/ptr"
	"go.mau.fi/util/variationselector"

	"go.mau.fi/mautrix-meta/pkg/instameow"
	"go.mau.fi/mautrix-meta/pkg/instameow/slidetypes"
	"go.mau.fi/mautrix-meta/pkg/messagix/dgw"
	"go.mau.fi/mautrix-meta/pkg/messagix/httpclient"
	"go.mau.fi/mautrix-meta/pkg/messagix/methods"
	"go.mau.fi/mautrix-meta/pkg/messagix/responses"
	"go.mau.fi/mautrix-meta/pkg/messagix/socket"
	"go.mau.fi/mautrix-meta/pkg/messagix/table"
	"go.mau.fi/mautrix-meta/pkg/messagix/types"
)

func (c *Client) connectInstagram() (*UserInfo, *InitialData, error) {
	if c.IG == nil {
		return nil, nil, errors.New("instagram client is not initialized")
	}
	currentUser, mailbox, err := c.IG.LoadIndex(c.ctx)
	if err != nil {
		return nil, nil, err
	}

	fbid := c.IG.GetOwnFBID()
	if fbid == 0 && currentUser != nil && currentUser.ID != "" {
		fbid, _ = strconv.ParseInt(currentUser.ID, 10, 64)
	}
	if fbid == 0 && c.IG.GetCookies() != nil {
		fbid = c.IG.GetCookies().GetUserID()
	}

	userInfo := &UserInfo{
		ID: fbid,
	}
	if currentUser != nil {
		userInfo.Name = currentUser.GetName()
		userInfo.Username = currentUser.GetUsername()
	}
	c.FBID = userInfo.ID

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

	c.regularConnected.Store(true)
	c.clearTransportFailure(false)
	c.emitEvent(EventTypeReady, map[string]any{
		"isNewSession": false,
	})

	go c.IG.Connect(c.ctx)

	return userInfo, initialData, nil
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
				pResp, pErr := c.IG.PaginateMailbox(ctx, slidetypes.MakePaginateMailboxRequest(c.FBID, cursor, "INBOX", nil))
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
		resp, err := c.IG.GetThread(c.ctx, slidetypes.MakeGetThreadInfoRequest(shortOrLongID))
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

func (c *Client) handleIGEvent(ctx context.Context, rawEvt slidetypes.ClientEvent) error {
	c.emitEvent(EventTypeRaw, &RawEvent{
		From: RawEventSourceLightSpeed,
		Type: getEventTypeName(rawEvt),
		Data: rawEvt,
	})

	switch evt := rawEvt.(type) {
	case *slidetypes.Connected:
		c.regularConnected.Store(true)
		c.clearTransportFailure(false)
		c.emitEvent(EventTypeReady, map[string]any{
			"isNewSession": false,
		})
		return nil

	case *slidetypes.Disconnected:
		if dgw.IsUnauthorized(evt.Error) || errors.Is(evt.Error, instameow.ErrUserIDMissing) {
			c.regularConnected.Store(false)
			c.emitConnectionFailure(false, permanentConnectionFailure(evt.Error))
			return fmt.Errorf("instagram dgw unauthorized: %w", evt.Error)
		}
		if evt.FailureCount > 5 && errors.Is(evt.Error, instameow.ErrMainStreamClosed) {
			c.regularConnected.Store(false)
			c.emitConnectionFailure(false, permanentConnectionFailure(evt.Error))
			return fmt.Errorf("instagram main stream closed repeatedly: %w", evt.Error)
		}
		c.regularConnected.Store(false)
		c.emitConnectionFailure(false, transientConnectionFailure(evt.Error))
		return nil

	case *slidetypes.AuthError:
		c.regularConnected.Store(false)
		c.emitConnectionFailure(false, permanentConnectionFailure(evt.Error))
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
		threadKey := c.resolveIGThreadKey(d.ThreadIGID)
		c.emitEvent(EventTypeMessageEdit, &MessageEditEvent{
			MessageID:   evt.MessageID,
			ThreadID:    threadKey,
			NewText:     evt.TextBody,
			TimestampMs: evt.SlideEditHistoryEntry.TimestampMS.UnixMilli(),
		})

	case *slidetypes.DeleteMessageEvent:
		threadKey := c.resolveIGThreadKey(d.ThreadIGID)
		c.emitEvent(EventTypeMessageUnsend, map[string]any{
			"messageId": evt.MessageID,
			"threadId":  threadKey,
		})

	case *slidetypes.CreateReactionEvent:
		threadKey := c.resolveIGThreadKey(d.ThreadIGID)
		c.emitEvent(EventTypeReaction, &ReactionEvent{
			MessageID:   evt.MessageID,
			ThreadID:    threadKey,
			ActorID:     evt.Reaction.SenderFBID,
			Reaction:    evt.Reaction.Reaction,
			TimestampMs: evt.Reaction.ReactionTimestampMS.UnixMilli(),
		})

	case *slidetypes.DeleteReactionEvent:
		threadKey := c.resolveIGThreadKey(d.ThreadIGID)
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
			ReaderID:                 c.FBID,
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
		c.emitEvent("threadUpdate", map[string]any{
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
		c.emitEvent("threadUpdate", map[string]any{
			"action":   "deleteThread",
			"threadId": threadKey,
		})

	case *slidetypes.UpdateThreadFolderEvent:
		threadKey := c.resolveIGThreadKey(d.ThreadIGID)
		c.emitEvent("threadUpdate", map[string]any{
			"action":        "updateFolder",
			"threadId":      threadKey,
			"folder":        evt.Folder,
			"igInboxFolder": evt.IGInboxFolder,
		})

	case *slidetypes.AdminChangeEvent:
		threadKey := c.resolveIGThreadKey(d.ThreadIGID)
		c.emitEvent("threadUpdate", map[string]any{
			"action":     "adminChange",
			"threadId":   threadKey,
			"adminIgids": evt.AdminIGIDs,
		})

	case *slidetypes.MuteThreadEvent:
		threadKey := c.resolveIGThreadKey(d.ThreadIGID)
		c.emitEvent("threadUpdate", map[string]any{
			"action":     "muteThread",
			"threadId":   threadKey,
			"isMutedNow": evt.IsMutedNow,
		})

	case *slidetypes.PinThreadEvent:
		threadKey := c.resolveIGThreadKey(d.ThreadIGID)
		c.emitEvent("threadUpdate", map[string]any{
			"action":   "pinThread",
			"threadId": threadKey,
			"isPinned": evt.IsPinned,
		})

	case *slidetypes.PinMessageEvent:
		threadKey := c.resolveIGThreadKey(d.ThreadIGID)
		c.emitEvent("threadUpdate", map[string]any{
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
	msgID := msg.ID
	if msgID == "" {
		msgID = msg.MessageID
	}
	if msgID != "" && !c.claimMessageID(msgID) {
		return
	}

	threadKey := c.resolveIGThreadKey(threadIGID)
	if threadKey == 0 && msg.SenderFBID != 0 && msg.SenderFBID != c.FBID {
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
		tsMs = time.Now().UnixMilli()
	}

	attachments := extractIGAttachments(msg.Content.Content)

	if c.igE2EEReady.Load() && !isAdmin {
		chatJID := fmt.Sprintf("%d@msgr", threadKey)
		senderJID := fmt.Sprintf("%d@msgr", msg.SenderFBID)
		c.emitEvent(EventTypeE2EEMessage, &E2EEMessage{
			ID:          msgID,
			ThreadID:    threadKey,
			ChatJID:     chatJID,
			SenderJID:   senderJID,
			SenderID:    msg.SenderFBID,
			Text:        text,
			TimestampMs: tsMs,
			Attachments: attachments,
			ReplyTo:     replyTo,
			Mentions:    mentions,
		})
		return
	}

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

func parseThreadKeyFromJID(chatJIDStr string) (int64, error) {
	trimmed := strings.TrimSpace(chatJIDStr)
	if trimmed == "" {
		return 0, errors.New("chat JID is empty")
	}
	userPart := trimmed
	if atIdx := strings.IndexByte(trimmed, '@'); atIdx >= 0 {
		userPart = trimmed[:atIdx]
	}
	if colonIdx := strings.IndexByte(userPart, ':'); colonIdx >= 0 {
		userPart = userPart[:colonIdx]
	}
	return strconv.ParseInt(userPart, 10, 64)
}

func (c *Client) sendIGMessage(opts *SendMessageOptions) (*SendMessageResult, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	threadKey := opts.ThreadID
	if threadKey == 0 && opts.E2EEChatJID != "" {
		parsed, err := parseThreadKeyFromJID(opts.E2EEChatJID)
		if err != nil {
			return nil, err
		}
		threadKey = parsed
	}
	ids, err := c.resolveIGThreadIDs(c.ctx, threadKey)
	if err != nil {
		return nil, err
	}

	otid := strconv.FormatInt(methods.GenerateEpochID(), 10)
	var replyToID *string
	if opts.ReplyToID != "" {
		replyToID = &opts.ReplyToID
	} else if opts.E2EEReplyToID != "" {
		replyToID = &opts.E2EEReplyToID
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
		if id == -1 || (threadKey != 0 && id == threadKey) {
			mType = socket.MentionTypeThread
			if shortInt, sErr := strconv.ParseInt(ids.ShortID, 10, 64); sErr == nil && shortInt != 0 {
				targetID = shortInt
			} else {
				targetID = threadKey
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
		targetThreadFBID := threadKey
		if shortInt, sErr := strconv.ParseInt(ids.ShortID, 10, 64); sErr == nil && shortInt != 0 {
			targetThreadFBID = shortInt
		}
		commands = append(commands, slidetypes.InputCommand{
			Offset:           idx,
			Length:           len("@everyone"),
			Type:             "EVERYONE",
			UserOrThreadFBID: targetThreadFBID,
		})
	}

	if len(opts.AttachmentFbIds) > 0 {
		var lastSent slidetypes.SentMessage
		for _, attID := range opts.AttachmentFbIds {
			resp, sendErr := c.IG.SendMedia(c.ctx, &slidetypes.SendMediaRequest{
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
		c.rememberIGMessageThread(msgID, ids.ShortID, ids.LongID)
		return &SendMessageResult{
			MessageID:      msgID,
			TimestampMs:    lastSent.TimestampMS.UnixMilli(),
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
	resp, err := c.IG.SendMessage(c.ctx, req)
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
		tsMs = time.Now().UnixMilli()
	}
	c.rememberIGMessageThread(msgID, ids.ShortID, ids.LongID)
	return &SendMessageResult{
		MessageID:      msgID,
		TimestampMs:    tsMs,
		DeliveryStatus: DeliveryStatusAcknowledged,
	}, nil
}

func (c *Client) sendIGReaction(threadKey int64, messageID, emoji string) error {
	var shortID string
	if cached := c.lookupIGMessageThread(messageID); cached != nil && cached.ShortID != "" {
		shortID = cached.ShortID
	} else {
		ids, err := c.resolveIGThreadIDs(c.ctx, threadKey)
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
	_, err := c.IG.SendReaction(c.ctx, &slidetypes.CreateReactionRequest{
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

func (c *Client) editIGMessage(threadKey int64, messageID, newText string) error {
	var shortID string
	if cached := c.lookupIGMessageThread(messageID); cached != nil && cached.ShortID != "" {
		shortID = cached.ShortID
	} else if threadKey != 0 {
		ids, err := c.resolveIGThreadIDs(c.ctx, threadKey)
		if err != nil {
			return err
		}
		shortID = ids.ShortID
	}
	_, err := c.IG.EditMessage(c.ctx, &slidetypes.EditMessageRequest{
		ThreadID:           shortID,
		TargetItemID:       "",
		Body:               slidetypes.SensitiveString{Value: newText},
		OfflineThreadingID: strconv.FormatInt(methods.GenerateEpochID(), 10),
		TargetMessageID:    messageID,
	})
	return err
}

func (c *Client) unsendIGMessage(threadKey int64, messageID string) error {
	var longID string
	if cached := c.lookupIGMessageThread(messageID); cached != nil && cached.LongID != "" {
		longID = cached.LongID
	} else if threadKey != 0 {
		ids, err := c.resolveIGThreadIDs(c.ctx, threadKey)
		if err != nil {
			return err
		}
		longID = ids.LongID
	}
	_, err := c.IG.UnsendMessage(c.ctx, &slidetypes.UnsendMessageRequest{
		MessageID: messageID,
		SendData: slidetypes.SendData{
			ThreadID: longID,
		},
	})
	return err
}

func (c *Client) markIGRead(threadKey int64, messageID string, watermarkTs int64) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ids, err := c.resolveIGThreadIDs(c.ctx, threadKey)
	if err != nil {
		return err
	}
	if messageID == "" {
		resp, err := c.IG.GetThread(c.ctx, slidetypes.MakeGetThreadInfoRequest(ids.ShortID))
		if err == nil && resp != nil && resp.ThreadInfo.AsIGDirectThread != nil && resp.ThreadInfo.AsIGDirectThread.SlideMessages != nil {
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
	}
	if messageID == "" {
		return nil
	}
	emptyItemID := ""
	_, err = c.IG.MarkRead(c.ctx, &slidetypes.MarkReadRequest{
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
		_, _ = c.IG.MarkReadValidation(c.ctx, &slidetypes.MarkReadRequest{
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

func (c *Client) muteIGThread(threadKey int64, muteSeconds int) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ids, err := c.resolveIGThreadIDs(c.ctx, threadKey)
	if err != nil {
		return err
	}
	_, err = c.IG.MuteThread(c.ctx, &slidetypes.MuteThreadRequest{
		ThreadID:           ids.ShortID,
		MuteSeconds:        muteSeconds,
		OfflineThreadingID: strconv.FormatInt(methods.GenerateEpochID(), 10),
	})
	return err
}

func (c *Client) pinIGThread(threadKey int64, pin bool) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ids, err := c.resolveIGThreadIDs(c.ctx, threadKey)
	if err != nil {
		return err
	}
	_, err = c.IG.PinThread(c.ctx, &slidetypes.PinThreadRequest{
		ThreadID: ids.ShortID,
		Pin:      pin,
	})
	return err
}

func (c *Client) pinIGMessage(threadKey int64, messageID string, pin bool) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	var shortID string
	if cached := c.lookupIGMessageThread(messageID); cached != nil && cached.ShortID != "" {
		shortID = cached.ShortID
	} else if threadKey != 0 {
		ids, err := c.resolveIGThreadIDs(c.ctx, threadKey)
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
		_, err := c.IG.PinMessage(c.ctx, req)
		return err
	}
	_, err := c.IG.UnpinMessage(c.ctx, req)
	return err
}

func (c *Client) deleteIGThread(threadKey int64, markAsSpam bool) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ids, err := c.resolveIGThreadIDs(c.ctx, threadKey)
	if err != nil {
		return err
	}
	_, err = c.IG.DeleteThread(c.ctx, &slidetypes.DeleteThreadRequest{
		ThreadID:   ids.ShortID,
		MarkAsSpam: markAsSpam,
	})
	if err == nil {
		c.mu.Lock()
		delete(c.threadCache, threadKey)
		c.mu.Unlock()
	}
	return err
}

func (c *Client) renameIGThread(threadKey int64, newName string) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ids, err := c.resolveIGThreadIDs(c.ctx, threadKey)
	if err != nil {
		return err
	}
	return c.IG.EditGroupTitle(c.ctx, ids.ShortID, newName)
}

func (c *Client) acceptIGMessageRequest(threadKey int64) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ids, err := c.resolveIGThreadIDs(c.ctx, threadKey)
	if err != nil {
		return err
	}
	_, err = c.IG.AcceptMessageRequest(c.ctx, &slidetypes.AcceptMessageRequestRequest{
		ThreadID:           ids.ShortID,
		OfflineThreadingID: strconv.FormatInt(methods.GenerateEpochID(), 10),
	})
	return err
}

func (c *Client) searchIGUsers(query string) ([]*SearchUser, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	resp, err := c.IG.SearchUsers(c.ctx, strings.TrimSpace(query))
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

func (c *Client) getIGUserInfo(userID int64) (*ContactInfo, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	resp, err := c.IG.GetUserForNewDM(c.ctx, userID)
	if err == nil && resp != nil && resp.Data != nil {
		u := resp.Data
		id := u.InteropMessagingUserFBID
		if id == 0 {
			id = userID
		}
		return &ContactInfo{
			ID:                id,
			Name:              u.FullName,
			Username:          u.Username,
			ProfilePictureUrl: u.ProfilePicURL,
			IsVerified:        u.IsVerified,
			IsMessengerUser:   true,
			CanViewerMessage:  true,
		}, nil
	}
	profileResp, profErr := c.IG.GetProfile(c.ctx, strconv.FormatInt(userID, 10))
	if profErr == nil && profileResp != nil && profileResp.User != nil {
		u := profileResp.User
		id := u.InteropMessagingUserFBID
		if id == 0 {
			id = userID
		}
		return &ContactInfo{
			ID:                id,
			Name:              u.FullName,
			Username:          u.Username,
			ProfilePictureUrl: u.ProfilePicURL,
			IsVerified:        u.IsVerified,
			IsMessengerUser:   true,
			CanViewerMessage:  true,
		}, nil
	}
	if err != nil {
		return nil, err
	}
	return nil, fmt.Errorf("user not found: %d", userID)
}

func (c *Client) uploadIGMedia(opts *UploadMediaOptions) (*UploadMediaResult, error) {
	if c.IG == nil || c.IG.GetHTTP() == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	media := &httpclient.MercuryUploadMedia{
		Filename:    opts.Filename,
		MimeType:    opts.MimeType,
		MediaData:   opts.Data,
		IsVoiceClip: opts.IsVoice,
	}
	resp, err := c.IG.GetHTTP().SendMercuryUploadRequest(c.ctx, opts.ThreadID, media)
	if err != nil {
		return nil, err
	}
	var fbid int64
	if resp.Payload.RealMetadata != nil {
		fbid = resp.Payload.RealMetadata.GetFbId()
	}
	return &UploadMediaResult{
		FbID:     fbid,
		Filename: opts.Filename,
	}, nil
}

func (c *Client) getIGInbox() ([]*Thread, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	mailboxResp, err := c.IG.GetMailbox(c.ctx)
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

// ThreadDetail represents detailed information and recent messages of a thread
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

func (c *Client) getIGThreadInfo(threadKey int64, messageLimit int) (*ThreadDetail, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	ids, err := c.resolveIGThreadIDs(c.ctx, threadKey)
	if err != nil {
		return nil, err
	}
	resp, err := c.IG.GetThread(c.ctx, slidetypes.MakeGetThreadInfoRequest(ids.ShortID))
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
			IsMessengerUser:   true,
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
			text := msg.TextBody
			var attachments []*Attachment
			if msg.Content.Content != nil {
				if text == "" {
					if txtContent, ok := msg.Content.Content.(*slidetypes.MessageContentText); ok && txtContent != nil {
						text = txtContent.TextBody
					} else if xmaContent, ok := msg.Content.Content.(*slidetypes.MessageContentXMA); ok && xmaContent != nil {
						text = xmaContent.XMATextBody
					}
				}
				attachments = extractIGAttachments(msg.Content.Content)
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
				Text:        text,
				TimestampMs: msg.TimestampMS.UnixMilli(),
				Attachments: attachments,
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
			pResp, pErr := c.IG.PaginateMessages(c.ctx, &slidetypes.PaginateMessagesRequest{
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
				text := msg.TextBody
				var attachments []*Attachment
				if msg.Content.Content != nil {
					if text == "" {
						if txtContent, ok := msg.Content.Content.(*slidetypes.MessageContentText); ok && txtContent != nil {
							text = txtContent.TextBody
						}
					}
					attachments = extractIGAttachments(msg.Content.Content)
				}
				messages = append(messages, &Message{
					ID:          msgID,
					ThreadID:    resolvedKey,
					ThreadName:  title,
					SenderID:    msg.SenderFBID,
					Text:        text,
					TimestampMs: msg.TimestampMS.UnixMilli(),
					Attachments: attachments,
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

func (c *Client) getIGMessageRequests() ([]*Thread, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	pResp, err := c.IG.PaginateMailbox(c.ctx, slidetypes.MakePaginateMailboxRequest(c.FBID, "", "PENDING", nil))
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

func (c *Client) sendIGMediaFromURL(threadKey int64, mediaURL, filename, mimeType, replyToID string, isVoice bool) (*SendMessageResult, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	parsedURL, err := url.Parse(strings.TrimSpace(mediaURL))
	if err != nil || (parsedURL.Scheme != "http" && parsedURL.Scheme != "https") {
		return nil, errors.New("invalid http/https media URL")
	}
	reqCtx, cancel := context.WithTimeout(c.ctx, 30*time.Second)
	defer cancel()
	httpReq, err := http.NewRequestWithContext(reqCtx, http.MethodGet, parsedURL.String(), nil)
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
	resp, err := http.DefaultClient.Do(httpReq)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("failed to download media: HTTP %d", resp.StatusCode)
	}
	const maxMediaBytes = 25 * 1024 * 1024
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxMediaBytes+1))
	if err != nil {
		return nil, err
	}
	if len(data) == 0 {
		return nil, errors.New("downloaded media is empty")
	}
	if len(data) > maxMediaBytes {
		return nil, errors.New("media exceeds 25 MiB limit")
	}
	if mimeType == "" {
		mimeType = resp.Header.Get("Content-Type")
		if semi := strings.IndexByte(mimeType, ';'); semi >= 0 {
			mimeType = strings.TrimSpace(mimeType[:semi])
		}
		if mimeType == "" || mimeType == "application/octet-stream" {
			mimeType = http.DetectContentType(data)
		}
	}
	if filename == "" {
		base := path.Base(parsedURL.Path)
		if base != "" && base != "/" && base != "." {
			filename = base
		} else if isVoice {
			filename = "voice.mp4"
		} else {
			filename = "media.jpg"
		}
	}
	uploaded, err := c.uploadIGMedia(&UploadMediaOptions{
		ThreadID: threadKey,
		Filename: filename,
		MimeType: mimeType,
		Data:     data,
		IsVoice:  isVoice,
	})
	if err != nil {
		return nil, err
	}
	return c.sendIGMessage(&SendMessageOptions{
		ThreadID:        threadKey,
		AttachmentFbIds: []int64{uploaded.FbID},
		ReplyToID:       replyToID,
	})
}

func (c *Client) createIGGroup(recipientFBIDs []int64, title string) (*Thread, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	seen := make(map[int64]bool)
	recips := make([]string, 0, len(recipientFBIDs))
	for _, id := range recipientFBIDs {
		if id != 0 && id != c.FBID && !seen[id] {
			seen[id] = true
			recips = append(recips, strconv.FormatInt(id, 10))
		}
	}
	if len(recips) < 2 {
		return nil, errors.New("instagram requires at least 2 other recipients to create a group chat")
	}
	resp, err := c.IG.CreateGroup(c.ctx, &slidetypes.CreateGroupRequest{
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
		_ = c.IG.EditGroupTitle(c.ctx, shortID, cleanTitle)
	}
	initText := "👋 Nhóm chat mới đã được tạo."
	if cleanTitle != "" {
		initText = fmt.Sprintf("👋 Nhóm %q đã được tạo.", cleanTitle)
	}
	_, _ = c.IG.SendMessage(c.ctx, &slidetypes.SendTextRequest{
		IGThreadIGID:       &shortID,
		OfflineThreadingID: strconv.FormatInt(methods.GenerateEpochID(), 10),
		Text:               slidetypes.SensitiveString{Value: initText},
		SendAttribution:    ptr.Ptr("igd_web_chat_tab:in_thread"),
	})
	if tResp, tErr := c.IG.GetThread(c.ctx, slidetypes.MakeGetThreadInfoRequest(shortID)); tErr == nil && tResp != nil && tResp.ThreadInfo.AsIGDirectThread != nil {
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

func (c *Client) addIGGroupMembers(threadKey int64, userIDs []int64) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ids, err := c.resolveIGThreadIDs(c.ctx, threadKey)
	if err != nil {
		return err
	}
	userStrs := make([]string, 0, len(userIDs))
	for _, uid := range userIDs {
		if uid != 0 {
			userStrs = append(userStrs, strconv.FormatInt(uid, 10))
		}
	}
	_, err = c.IG.AddMembers(c.ctx, slidetypes.MakeAddMembersRequest(ids.ShortID, userStrs...))
	return err
}

func (c *Client) removeIGGroupMember(threadKey int64, userID int64) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ids, err := c.resolveIGThreadIDs(c.ctx, threadKey)
	if err != nil {
		return err
	}
	_, err = c.IG.RemoveMember(c.ctx, &slidetypes.RemoveMemberRequest{
		ThreadID: ids.ShortID,
		UserIGID: strconv.FormatInt(userID, 10),
	})
	return err
}

func (c *Client) modifyIGGroupAdmins(threadKey int64, userIDs []int64, promote bool) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ids, err := c.resolveIGThreadIDs(c.ctx, threadKey)
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
		_, err = c.IG.AddAdmins(c.ctx, req)
		return err
	}
	_, err = c.IG.RemoveAdmins(c.ctx, req)
	return err
}

func (c *Client) leaveIGGroup(threadKey int64) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ids, err := c.resolveIGThreadIDs(c.ctx, threadKey)
	if err != nil {
		return err
	}
	_, err = c.IG.LeaveGroup(c.ctx, &slidetypes.LeaveThreadRequest{
		ThreadID: ids.ShortID,
	})
	return err
}

func (c *Client) editIGGroupAvatar(threadKey int64, avatarData []byte) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ids, err := c.resolveIGThreadIDs(c.ctx, threadKey)
	if err != nil {
		return err
	}
	if len(avatarData) == 0 {
		return c.IG.RemoveGroupAvatar(c.ctx, ids.LongID)
	}
	return c.IG.EditGroupAvatar(c.ctx, ids.LongID, avatarData)
}

func (c *Client) setIGUserBlocked(userID string, blocked bool) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	trimmed := strings.TrimSpace(userID)
	if trimmed == "" {
		return errors.New("user ID is required")
	}
	return c.IG.SetUserBlocked(c.ctx, trimmed, blocked)
}

// FetchedMediaInfo holds metadata and direct CDN URLs for an Instagram post/reel
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

func (c *Client) fetchIGMedia(input string) (*FetchedMediaInfo, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	mediaID, shortcode := extractShortcodeFromInput(input)
	if mediaID == "" {
		return nil, fmt.Errorf("invalid media ID or shortcode: %s", input)
	}
	resp, err := c.IG.FetchMedia(c.ctx, mediaID, shortcode)
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

func (c *Client) editIGGroupAvatarFromURL(threadKey int64, imageURL string) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	trimmed := strings.TrimSpace(imageURL)
	if trimmed == "" || strings.EqualFold(trimmed, "clear") || strings.EqualFold(trimmed, "remove") {
		return c.editIGGroupAvatar(threadKey, nil)
	}
	parsedURL, err := url.Parse(trimmed)
	if err != nil || (parsedURL.Scheme != "http" && parsedURL.Scheme != "https") {
		return errors.New("invalid http/https image URL")
	}
	reqCtx, cancel := context.WithTimeout(c.ctx, 20*time.Second)
	defer cancel()
	httpReq, err := http.NewRequestWithContext(reqCtx, http.MethodGet, parsedURL.String(), nil)
	if err != nil {
		return err
	}
	httpReq.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
	resp, err := http.DefaultClient.Do(httpReq)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("failed to download avatar image: HTTP %d", resp.StatusCode)
	}
	const maxAvatarBytes = 10 * 1024 * 1024
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxAvatarBytes+1))
	if err != nil {
		return err
	}
	if len(data) == 0 || len(data) > maxAvatarBytes {
		return errors.New("invalid avatar image size")
	}
	return c.editIGGroupAvatar(threadKey, data)
}

func (c *Client) forwardIGMessage(sourceThreadKey, targetThreadKey int64, messageID, customText string) (*SendMessageResult, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	if targetThreadKey == 0 {
		return nil, errors.New("target thread ID is required")
	}
	targetIDs, err := c.resolveIGThreadIDs(c.ctx, targetThreadKey)
	if err != nil {
		return nil, err
	}
	var sourceLongID *string
	isOwn := false
	textToSend := strings.TrimSpace(customText)
	var mediaURLToSend string

	if sourceThreadKey != 0 {
		if sourceIDs, sErr := c.resolveIGThreadIDs(c.ctx, sourceThreadKey); sErr == nil && sourceIDs != nil {
			if sourceIDs.LongID != "" {
				sourceLongID = &sourceIDs.LongID
			}
			if messageID != "" && textToSend == "" {
				if tResp, tErr := c.IG.GetThread(c.ctx, slidetypes.MakeGetThreadInfoRequest(sourceIDs.ShortID)); tErr == nil && tResp != nil && tResp.ThreadInfo.AsIGDirectThread != nil && tResp.ThreadInfo.AsIGDirectThread.SlideMessages != nil {
					for _, edge := range tResp.ThreadInfo.AsIGDirectThread.SlideMessages.Edges {
						m := edge.Node
						if m == nil {
							continue
						}
						if m.ID == messageID || m.MessageID == messageID {
							isOwn = m.SenderFBID == c.FBID
							textToSend = m.TextBody
							if textToSend == "" && m.Content.Content != nil {
								if txtContent, ok := m.Content.Content.(*slidetypes.MessageContentText); ok && txtContent != nil {
									textToSend = txtContent.TextBody
								}
							}
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
		return c.sendIGMediaFromURL(targetThreadKey, mediaURLToSend, "", "", "", false)
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
	resp, err := c.IG.SendMessage(c.ctx, req)
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
		tsMs = time.Now().UnixMilli()
	}
	c.rememberIGMessageThread(msgID, targetIDs.ShortID, targetIDs.LongID)
	return &SendMessageResult{
		MessageID:      msgID,
		TimestampMs:    tsMs,
		DeliveryStatus: DeliveryStatusAcknowledged,
	}, nil
}

// WebProfilePost represents a recent timeline post from a user's profile
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

// WebProfileInfo holds comprehensive profile details for an Instagram user
type WebProfileInfo struct {
	ID                string            `json:"id"`
	FBID              int64             `json:"fbid,omitempty"`
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

func (c *Client) getIGWebProfile(identifier string) (*WebProfileInfo, error) {
	if c.IG == nil || c.IG.GetHTTP() == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	clean := strings.TrimPrefix(strings.TrimSpace(identifier), "@")
	if clean == "" {
		return nil, errors.New("username or user ID is required")
	}

	var resolvedUsername string
	var resolvedIGID string
	var fallbackInfo *WebProfileInfo

	applyGraphQLProfile := func(u *slidetypes.User, knownFBID int64) *WebProfileInfo {
		if u == nil {
			return nil
		}
		uid := u.PK
		if uid == "" {
			uid = u.ID
		}
		fbid := u.InteropMessagingUserFBID
		if fbid == 0 && knownFBID > 0 {
			fbid = knownFBID
		}
		if fbid == 0 && u.FBIDV2 != "" {
			fbid, _ = strconv.ParseInt(u.FBIDV2, 10, 64)
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
			FBID:              fbid,
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
		if dmResp, dmErr := c.IG.GetUserForNewDM(c.ctx, numericID); dmErr == nil && dmResp != nil && dmResp.Data != nil {
			u := dmResp.Data
			resolvedUsername = u.Username
			uid := u.PK
			if uid == "" {
				uid = u.ID
			}
			resolvedIGID = uid
			fbid := u.InteropMessagingUserFBID
			if fbid == 0 {
				fbid = numericID
			}
			fallbackInfo = &WebProfileInfo{
				ID:            uid,
				FBID:          fbid,
				Username:      u.Username,
				FullName:      u.FullName,
				ProfilePicURL: u.ProfilePicURL,
				IsVerified:    u.IsVerified,
			}
		} else {
			resolvedIGID = clean
		}
		if resolvedIGID != "" {
			if profResp, profErr := c.IG.GetProfile(c.ctx, resolvedIGID); profErr == nil && profResp != nil && profResp.User != nil {
				knownFBID := int64(0)
				if fallbackInfo != nil {
					knownFBID = fallbackInfo.FBID
				}
				fallbackInfo = applyGraphQLProfile(profResp.User, knownFBID)
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
		_, respBody, err := c.IG.GetHTTP().MakeRequest(c.ctx, reqURL, http.MethodGet, h, nil, types.NONE)
		if err == nil && len(respBody) > 0 {
			var webProf responses.ProfileInfoResponse
			if jsonErr := json.Unmarshal(respBody, &webProf); jsonErr == nil && webProf.Data.User.Username != "" {
				u := webProf.Data.User
				var fbid int64
				if u.EimuID != "" {
					fbid, _ = strconv.ParseInt(u.EimuID, 10, 64)
				}
				if fbid == 0 && u.Fbid != "" {
					fbid, _ = strconv.ParseInt(u.Fbid, 10, 64)
				}
				if fbid == 0 && fallbackInfo != nil {
					fbid = fallbackInfo.FBID
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
					FBID:              fbid,
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

	if searchResp, sErr := c.IG.SearchUsers(c.ctx, clean); sErr == nil && searchResp != nil {
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
					if profResp, profErr := c.IG.GetProfile(c.ctx, pk); profErr == nil && profResp != nil && profResp.User != nil {
						if fullProf := applyGraphQLProfile(profResp.User, r.InteropMessagingUserFBID); fullProf != nil {
							return fullProf, nil
						}
					}
				}
				return &WebProfileInfo{
					ID:            pk,
					FBID:          r.InteropMessagingUserFBID,
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

// StoryItemInfo holds metadata and media URL for a single Instagram story item
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

// FetchedStoriesResult holds all active story items for an Instagram user or highlight
type FetchedStoriesResult struct {
	UserID   string           `json:"userId"`
	Username string           `json:"username,omitempty"`
	FullName string           `json:"fullName,omitempty"`
	Count    int              `json:"count"`
	Items    []*StoryItemInfo `json:"items"`
}

func (c *Client) fetchIGStories(identifier string) (*FetchedStoriesResult, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	clean := strings.TrimPrefix(strings.TrimSpace(identifier), "@")
	if clean == "" {
		return nil, errors.New("username or user ID is required")
	}

	reelID := clean
	username := ""
	fullName := ""

	if !strings.HasPrefix(clean, "highlight:") {
		if prof, err := c.getIGWebProfile(clean); err == nil && prof != nil && prof.ID != "" {
			reelID = prof.ID
			username = prof.Username
			fullName = prof.FullName
		}
	}

	resp, err := c.IG.FetchReel(c.ctx, []string{reelID}, "")
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

// PaginatedInboxResult holds a page of Instagram threads and pagination state
type PaginatedInboxResult struct {
	Threads     []*Thread `json:"threads"`
	NextCursor  string    `json:"nextCursor,omitempty"`
	HasNextPage bool      `json:"hasNextPage"`
}

func (c *Client) paginateIGInbox(cursor, folder string) (*PaginatedInboxResult, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	targetFolder := strings.TrimSpace(folder)
	if targetFolder == "" {
		targetFolder = "INBOX"
	}
	if strings.TrimSpace(cursor) == "" && strings.EqualFold(targetFolder, "INBOX") {
		mbResp, err := c.IG.GetMailbox(c.ctx)
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
	pResp, err := c.IG.PaginateMailbox(c.ctx, slidetypes.MakePaginateMailboxRequest(c.FBID, cursor, targetFolder, nil))
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

// PaginatedMessagesResult holds a page of thread messages and pagination state
type PaginatedMessagesResult struct {
	ThreadID    int64      `json:"threadId"`
	Messages    []*Message `json:"messages"`
	NextCursor  string     `json:"nextCursor,omitempty"`
	HasNextPage bool       `json:"hasNextPage"`
}

func (c *Client) paginateIGMessages(threadKey int64, cursor string, limit int) (*PaginatedMessagesResult, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	ids, err := c.resolveIGThreadIDs(c.ctx, threadKey)
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
	pResp, err := c.IG.PaginateMessages(c.ctx, &slidetypes.PaginateMessagesRequest{
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

func (c *Client) getIGUnreadCount() (map[string]any, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	count, err := c.IG.GetUnreadThreadCount(c.ctx)
	if err != nil {
		return nil, err
	}
	return map[string]any{"unreadCount": count}, nil
}

