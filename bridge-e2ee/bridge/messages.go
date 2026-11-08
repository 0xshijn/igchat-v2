package bridge

import (
	"context"
	"errors"
	"strconv"
	"strings"
	"time"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waCommon"
	"go.mau.fi/whatsmeow/proto/waConsumerApplication"
	"go.mau.fi/whatsmeow/proto/waMsgApplication"
	waTypes "go.mau.fi/whatsmeow/types"

	"go.mau.fi/mautrix-meta/pkg/messagix/methods"
	"go.mau.fi/mautrix-meta/pkg/messagix/socket"
	"go.mau.fi/mautrix-meta/pkg/messagix/table"
	"go.mau.fi/mautrix-meta/pkg/messagix/types"
)

// SendMessageOptions for sending messages
type SendMessageOptions struct {
	ThreadID        int64   `json:"threadId"`
	Text            string  `json:"text"`
	ReplyToID       string  `json:"replyToId,omitempty"`
	MentionIDs      []int64 `json:"mentionIds,omitempty"`
	MentionOffsets  []int   `json:"mentionOffsets,omitempty"`
	MentionLengths  []int   `json:"mentionLengths,omitempty"`
	AttachmentFbIds []int64 `json:"attachmentFbIds,omitempty"`
	StickerID       int64   `json:"stickerId,omitempty"`
	Url             string  `json:"url,omitempty"`
	IsE2EE          bool    `json:"isE2EE,omitempty"`
	E2EEChatJID     string  `json:"e2eeChatJid,omitempty"`
	// E2EE Reply fields
	E2EEReplyToID        string `json:"e2eeReplyToId,omitempty"`
	E2EEReplyToSenderJID string `json:"e2eeReplyToSenderJid,omitempty"`
}

// SendMessageResult result of sending a message
type SendMessageResult struct {
	MessageID      string `json:"messageId"`
	TimestampMs    int64  `json:"timestampMs"`
	DeliveryStatus string `json:"deliveryStatus,omitempty"`
}

const (
	DeliveryStatusAcknowledged = "acknowledged"
	DeliveryStatusUnknown      = "unknown"
)

// SendMessage sends a text message
func (c *Client) SendMessage(opts *SendMessageOptions) (*SendMessageResult, error) {
	if opts.IsE2EE {
		if !c.IsE2EEConnected() {
			return nil, ErrE2EENotConnected
		}
		return c.sendE2EEMessage(opts)
	}
	return c.sendRegularMessage(opts)
}

func (c *Client) sendRegularMessage(opts *SendMessageOptions) (*SendMessageResult, error) {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.sendIGMessage(opts)
	}
	if err := c.Messagix.WaitUntilCanSendMessages(c.ctx, 10*time.Second); err != nil {
		return nil, err
	}

	otid := time.Now().UnixNano()
	sendType := table.TEXT

	if opts.StickerID > 0 {
		sendType = table.STICKER
	} else if len(opts.AttachmentFbIds) > 0 {
		sendType = table.MEDIA
	} else if opts.Url != "" {
		sendType = table.EXTERNAL_MEDIA
	}

	task := &socket.SendMessageTask{
		ThreadId:        opts.ThreadID,
		Otid:            otid,
		Text:            opts.Text,
		Source:          table.MESSENGER_INBOX_IN_THREAD,
		SendType:        sendType,
		SyncGroup:       1,
		StickerId:       opts.StickerID,
		Url:             opts.Url,
		AttachmentFBIds: opts.AttachmentFbIds,
	}

	// Handle reply
	if opts.ReplyToID != "" {
		task.ReplyMetaData = &socket.ReplyMetaData{
			ReplyMessageId:  opts.ReplyToID,
			ReplySourceType: 1,
			ReplyType:       0,
		}
	}

	// Handle mentions
	if len(opts.MentionIDs) > 0 {
		task.MentionData = buildMentionData(opts.MentionIDs, opts.MentionOffsets, opts.MentionLengths)
	}

	resp, err := c.Messagix.ExecuteTasks(c.ctx, task)
	if err != nil {
		return nil, err
	}

	result := &SendMessageResult{
		MessageID:   generateMID(otid),
		TimestampMs: time.Now().UnixMilli(),
	}

	// Try to get actual message ID from response
	otidStr := strconv.FormatInt(otid, 10)
	if resp != nil {
		for _, r := range resp.LSReplaceOptimsiticMessage {
			if r.OfflineThreadingId == otidStr {
				result.MessageID = r.MessageId
				break
			}
		}
	}

	return result, nil
}

func (c *Client) sendE2EEMessage(opts *SendMessageOptions) (*SendMessageResult, error) {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.sendIGMessage(opts)
	}
	e2eeClient := c.snapshotE2EEClient()
	if e2eeClient == nil || !e2eeClient.IsConnected() {
		return nil, ErrE2EENotConnected
	}

	chatJID, err := parseJID(opts.E2EEChatJID)
	if err != nil {
		return nil, err
	}
	if err = c.ensureE2EEDM(chatJID); err != nil {
		return nil, err
	}

	waMsg := &waConsumerApplication.ConsumerApplication{
		Payload: &waConsumerApplication.ConsumerApplication_Payload{
			Payload: &waConsumerApplication.ConsumerApplication_Payload_Content{
				Content: &waConsumerApplication.ConsumerApplication_Content{
					Content: &waConsumerApplication.ConsumerApplication_Content_MessageText{
						MessageText: &waCommon.MessageText{Text: &opts.Text},
					},
				},
			},
		},
	}

	// Build metadata for reply if specified
	var metadata *waMsgApplication.MessageApplication_Metadata
	if opts.E2EEReplyToID != "" {
		metadata = &waMsgApplication.MessageApplication_Metadata{
			QuotedMessage: &waMsgApplication.MessageApplication_Metadata_QuotedMessage{
				StanzaID: &opts.E2EEReplyToID,
			},
		}
		if opts.E2EEReplyToSenderJID != "" {
			metadata.QuotedMessage.Participant = &opts.E2EEReplyToSenderJID
		}
	}

	msgID := strconv.FormatInt(time.Now().UnixNano(), 10)
	resp, err := e2eeClient.SendFBMessage(c.ctx, chatJID, waMsg, metadata, whatsmeow.SendRequestExtra{ID: msgID})
	if err != nil {
		if isE2EESendResponseTimeout(err) {
			return newUnknownE2EESendResult(msgID, time.Now()), nil
		}
		return nil, err
	}

	return &SendMessageResult{
		MessageID:      msgID,
		TimestampMs:    resp.Timestamp.UnixMilli(),
		DeliveryStatus: DeliveryStatusAcknowledged,
	}, nil
}

func newUnknownE2EESendResult(messageID string, timestamp time.Time) *SendMessageResult {
	return &SendMessageResult{
		MessageID:      messageID,
		TimestampMs:    timestamp.UnixMilli(),
		DeliveryStatus: DeliveryStatusUnknown,
	}
}

func (c *Client) ensureE2EEDM(chatJID waTypes.JID) error {
	if chatJID.Server != waTypes.MessengerServer || chatJID.User == "" {
		return nil
	}

	threadID, err := strconv.ParseInt(chatJID.User, 10, 64)
	if err != nil {
		return err
	}

	resp, err := c.Messagix.ExecuteTasks(c.ctx, &socket.CreateWhatsAppThreadTask{
		WAJID:            threadID,
		OfflineThreadKey: methods.GenerateEpochID(),
		ThreadType:       table.ENCRYPTED_OVER_WA_ONE_TO_ONE,
		FolderType:       table.INBOX,
		BumpTimestampMS:  time.Now().UnixMilli(),
		TAMThreadSubtype: 0,
	})
	if err != nil {
		return err
	}

	if resp == nil || len(resp.LSIssueNewTask) == 0 {
		return nil
	}
	tasks := make([]socket.Task, len(resp.LSIssueNewTask))
	for idx, task := range resp.LSIssueNewTask {
		tasks[idx] = task
	}
	_, err = c.Messagix.ExecuteTasks(c.ctx, tasks...)
	return err
}

func isE2EESendResponseTimeout(err error) bool {
	if err == nil {
		return false
	}
	return strings.Contains(strings.ToLower(err.Error()), "timed out waiting for message send response")
}

// SendReaction sends a reaction to a message
func (c *Client) SendReaction(threadID int64, messageID, emoji string) error {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.sendIGReaction(threadID, messageID, emoji)
	}
	task := &socket.SendReactionTask{
		ThreadKey:       threadID,
		MessageID:       messageID,
		Reaction:        emoji,
		ActorID:         c.FBID,
		SendAttribution: table.MESSENGER_INBOX_IN_THREAD,
	}
	_, err := c.Messagix.ExecuteTasks(c.ctx, task)
	return err
}

// SendE2EEReaction sends an E2EE reaction
func (c *Client) SendE2EEReaction(chatJIDStr, messageID, senderJIDStr, emoji string) error {
	if c.Platform == types.Instagram && c.IG != nil {
		if !c.IsE2EEConnected() {
			return ErrE2EENotConnected
		}
		threadKey, err := parseThreadKeyFromJID(chatJIDStr)
		if err != nil {
			return err
		}
		return c.sendIGReaction(threadKey, messageID, emoji)
	}
	e2eeClient := c.snapshotE2EEClient()
	if e2eeClient == nil || !e2eeClient.IsConnected() {
		return ErrE2EENotConnected
	}

	chatJID, err := parseJID(chatJIDStr)
	if err != nil {
		return err
	}
	senderJID, err := parseJID(senderJIDStr)
	if err != nil {
		return err
	}

	msgKey := e2eeClient.BuildMessageKey(chatJID, senderJID, messageID)
	reactionMsg := &waConsumerApplication.ConsumerApplication{
		Payload: &waConsumerApplication.ConsumerApplication_Payload{
			Payload: &waConsumerApplication.ConsumerApplication_Payload_Content{
				Content: &waConsumerApplication.ConsumerApplication_Content{
					Content: &waConsumerApplication.ConsumerApplication_Content_ReactionMessage{
						ReactionMessage: &waConsumerApplication.ConsumerApplication_ReactionMessage{
							Key:  msgKey,
							Text: &emoji,
						},
					},
				},
			},
		},
	}

	reactionID := strconv.FormatInt(time.Now().UnixNano(), 10)
	_, err = e2eeClient.SendFBMessage(c.ctx, chatJID, reactionMsg, nil, whatsmeow.SendRequestExtra{ID: reactionID})
	return err
}

// EditMessage edits a message
func (c *Client) EditMessage(messageID, newText string) error {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.editIGMessage(0, messageID, newText)
	}
	task := &socket.EditMessageTask{
		MessageID: messageID,
		Text:      newText,
	}
	_, err := c.Messagix.ExecuteTasks(c.ctx, task)
	return err
}

// UnsendMessage unsends/deletes a message
func (c *Client) UnsendMessage(messageID string) error {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.unsendIGMessage(0, messageID)
	}
	task := &socket.DeleteMessageTask{
		MessageId: messageID,
	}
	_, err := c.Messagix.ExecuteTasks(c.ctx, task)
	return err
}

// SendTypingIndicator sends a typing indicator
func (c *Client) SendTypingIndicator(threadID int64, isTyping bool, isGroup bool, threadType int64) error {
	if c.Platform == types.Instagram && c.IG != nil {
		ids, err := c.resolveIGThreadIDs(c.ctx, threadID)
		if err != nil {
			return err
		}
		return c.IG.SetTyping(c.ctx, ids.ShortID, isTyping)
	}
	typingVal, groupVal := int64(0), int64(0)
	if isTyping {
		typingVal = 1
	}
	if isGroup {
		groupVal = 1
	}

	task := &socket.UpdatePresenceTask{
		ThreadKey:     threadID,
		IsGroupThread: groupVal,
		IsTyping:      typingVal,
		Attribution:   0,
		SyncGroup:     1,
		ThreadType:    threadType,
	}
	return c.Messagix.ExecuteStatelessTask(c.ctx, task)
}

// MarkRead marks messages as read
func (c *Client) MarkRead(threadID int64, watermarkTs int64) error {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.markIGRead(threadID, "", watermarkTs)
	}
	if watermarkTs == 0 {
		watermarkTs = time.Now().UnixMilli()
	}
	task := &socket.ThreadMarkReadTask{
		ThreadId:            threadID,
		LastReadWatermarkTs: watermarkTs,
		SyncGroup:           1,
	}
	_, err := c.Messagix.ExecuteTasks(c.ctx, task)
	return err
}

// PinMessage pins a message in a thread
func (c *Client) PinMessage(threadID int64, messageID string) error {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.pinIGMessage(threadID, messageID, true)
	}
	return nil
}

// UnpinMessage unpins a message in a thread
func (c *Client) UnpinMessage(threadID int64, messageID string) error {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.pinIGMessage(threadID, messageID, false)
	}
	return nil
}

// PinThread pins or unpins a thread
func (c *Client) PinThread(threadID int64, pin bool) error {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.pinIGThread(threadID, pin)
	}
	return nil
}

// AcceptMessageRequest accepts a message request for a thread
func (c *Client) AcceptMessageRequest(threadID int64) error {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.acceptIGMessageRequest(threadID)
	}
	return nil
}

// GetInbox returns cached/fresh inbox threads
func (c *Client) GetInbox() ([]*Thread, error) {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.getIGInbox()
	}
	c.mu.RLock()
	defer c.mu.RUnlock()
	threads := make([]*Thread, 0, len(c.threadCache))
	for _, t := range c.threadCache {
		threads = append(threads, t)
	}
	return threads, nil
}

// GetThreadInfo returns detailed thread metadata and recent messages
func (c *Client) GetThreadInfo(threadID int64, messageLimit int) (*ThreadDetail, error) {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.getIGThreadInfo(threadID, messageLimit)
	}
	c.mu.RLock()
	t := c.threadCache[threadID]
	c.mu.RUnlock()
	if t == nil {
		return &ThreadDetail{ID: threadID}, nil
	}
	return &ThreadDetail{
		ID:      t.ID,
		Name:    t.Name,
		IsGroup: t.Type == int(table.GROUP_THREAD),
	}, nil
}

// GetMessageRequests returns pending message request threads
func (c *Client) GetMessageRequests() ([]*Thread, error) {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.getIGMessageRequests()
	}
	return []*Thread{}, nil
}

// SendMediaFromURL downloads media from an HTTP/HTTPS URL and sends it to a thread
func (c *Client) SendMediaFromURL(threadID int64, mediaURL, filename, mimeType, replyToID string, isVoice bool) (*SendMessageResult, error) {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.sendIGMediaFromURL(threadID, mediaURL, filename, mimeType, replyToID, isVoice)
	}
	return nil, errors.New("sendMediaFromURL is only supported on Instagram")
}

// EditGroupAvatarFromURL updates or clears a group thread's avatar using an image URL
func (c *Client) EditGroupAvatarFromURL(threadID int64, imageURL string) error {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.editIGGroupAvatarFromURL(threadID, imageURL)
	}
	return errors.New("editGroupAvatarFromURL is only supported on Instagram")
}

// ForwardThreadMessage forwards a message from a source thread to a target thread
func (c *Client) ForwardThreadMessage(sourceThreadID, targetThreadID int64, messageID, customText string) (*SendMessageResult, error) {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.forwardIGMessage(sourceThreadID, targetThreadID, messageID, customText)
	}
	return nil, errors.New("forwardMessage is only supported on Instagram")
}

// GetWebProfile fetches comprehensive profile info by @username or user ID
func (c *Client) GetWebProfile(identifier string) (*WebProfileInfo, error) {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.getIGWebProfile(identifier)
	}
	return nil, errors.New("getWebProfile is only supported on Instagram")
}

// FetchStories fetches active 24h stories or highlights for a user
func (c *Client) FetchStories(identifier string) (*FetchedStoriesResult, error) {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.fetchIGStories(identifier)
	}
	return nil, errors.New("fetchStories is only supported on Instagram")
}

// CreateGroup creates a new group thread
func (c *Client) CreateGroup(userIDs []int64, title string) (*Thread, error) {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.createIGGroup(userIDs, title)
	}
	return nil, errors.New("createGroup is only supported on Instagram")
}

// AddGroupMembers adds members to a group thread
func (c *Client) AddGroupMembers(threadID int64, userIDs []int64) error {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.addIGGroupMembers(threadID, userIDs)
	}
	return errors.New("addGroupMembers is only supported on Instagram")
}

// RemoveGroupMember removes a member from a group thread
func (c *Client) RemoveGroupMember(threadID int64, userID int64) error {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.removeIGGroupMember(threadID, userID)
	}
	return errors.New("removeGroupMember is only supported on Instagram")
}

// ModifyGroupAdmins promotes or demotes group admins
func (c *Client) ModifyGroupAdmins(threadID int64, userIDs []int64, promote bool) error {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.modifyIGGroupAdmins(threadID, userIDs, promote)
	}
	return errors.New("modifyGroupAdmins is only supported on Instagram")
}

// LeaveGroup leaves a group thread
func (c *Client) LeaveGroup(threadID int64) error {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.leaveIGGroup(threadID)
	}
	return errors.New("leaveGroup is only supported on Instagram")
}

// SetUserBlocked blocks or unblocks a user
func (c *Client) SetUserBlocked(userID string, blocked bool) error {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.setIGUserBlocked(userID, blocked)
	}
	return errors.New("setUserBlocked is only supported on Instagram")
}

// PaginateInbox fetches a page of Instagram threads by cursor and folder
func (c *Client) PaginateInbox(cursor, folder string) (*PaginatedInboxResult, error) {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.paginateIGInbox(cursor, folder)
	}
	return nil, errors.New("paginateInbox is only supported on Instagram")
}

// PaginateMessages fetches older messages in an Instagram thread by cursor
func (c *Client) PaginateMessages(threadID int64, cursor string, limit int) (*PaginatedMessagesResult, error) {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.paginateIGMessages(threadID, cursor, limit)
	}
	return nil, errors.New("paginateMessages is only supported on Instagram")
}

// GetUnreadCount fetches the total unread thread count via GraphQL and local cache
func (c *Client) GetUnreadCount() (map[string]interface{}, error) {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.getIGUnreadCount()
	}
	return nil, errors.New("getUnreadCount is only supported on Instagram")
}

// FetchMedia fetches an Instagram post or reel by URL, shortcode, or media ID
func (c *Client) FetchMedia(input string) (*FetchedMediaInfo, error) {
	if c.Platform == types.Instagram && c.IG != nil {
		return c.fetchIGMedia(input)
	}
	return nil, errors.New("fetchMedia is only supported on Instagram")
}

// Helper functions
func buildMentionData(ids []int64, offsets, lengths []int) *socket.MentionData {
	var idStrs, offsetStrs, lengthStrs, typeStrs []string
	for i, id := range ids {
		idStrs = append(idStrs, strconv.FormatInt(id, 10))
		if i < len(offsets) {
			offsetStrs = append(offsetStrs, strconv.Itoa(offsets[i]))
		}
		if i < len(lengths) {
			lengthStrs = append(lengthStrs, strconv.Itoa(lengths[i]))
		}
		typeStrs = append(typeStrs, "p")
	}
	return &socket.MentionData{
		MentionIDs:     joinStrings(idStrs),
		MentionOffsets: joinStrings(offsetStrs),
		MentionLengths: joinStrings(lengthStrs),
		MentionTypes:   joinStrings(typeStrs),
	}
}

func joinStrings(strs []string) string {
	result := ""
	for i, s := range strs {
		if i > 0 {
			result += ","
		}
		result += s
	}
	return result
}

func generateMID(otid int64) string {
	return "mid.$" + strconv.FormatInt(otid, 10)
}

func parseJID(jidStr string) (waTypes.JID, error) {
	if jidStr == "" {
		return waTypes.EmptyJID, nil
	}
	return waTypes.ParseJID(jidStr)
}

// E2EE send typing
func (c *Client) SendE2EETyping(chatJIDStr string, isTyping bool) error {
	if c.Platform == types.Instagram && c.IG != nil {
		if !c.IsE2EEConnected() {
			return ErrE2EENotConnected
		}
		threadKey, err := parseThreadKeyFromJID(chatJIDStr)
		if err != nil {
			return err
		}
		ids, err := c.resolveIGThreadIDs(c.ctx, threadKey)
		if err != nil {
			return err
		}
		return c.IG.SetTyping(c.ctx, ids.ShortID, isTyping)
	}
	e2eeClient := c.snapshotE2EEClient()
	if e2eeClient == nil {
		return ErrE2EENotConnected
	}
	return c.sendE2EETyping(e2eeClient, chatJIDStr, isTyping)
}

const e2eeTypingTimeout = 10 * time.Second

type e2eeTypingSender interface {
	e2eeConnectionState
	SendChatPresence(context.Context, waTypes.JID, waTypes.ChatPresence, waTypes.ChatPresenceMedia) error
}

func (c *Client) sendE2EETyping(e2eeClient e2eeTypingSender, chatJIDStr string, isTyping bool) error {
	if err := c.lifecycleError(); err != nil {
		return err
	}
	if !isE2EEReady(e2eeClient) {
		return ErrE2EENotConnected
	}

	chatJID, err := parseJID(chatJIDStr)
	if err != nil {
		return err
	}

	presence := waTypes.ChatPresencePaused
	if isTyping {
		presence = waTypes.ChatPresenceComposing
	}
	ctx, cancel := context.WithTimeout(c.ctx, e2eeTypingTimeout)
	defer cancel()
	return e2eeClient.SendChatPresence(ctx, chatJID, presence, waTypes.ChatPresenceMediaText)
}

// EditE2EEMessage edits an E2EE message
func (c *Client) EditE2EEMessage(chatJIDStr, messageID, newText string) error {
	if c.Platform == types.Instagram && c.IG != nil {
		if !c.IsE2EEConnected() {
			return ErrE2EENotConnected
		}
		threadKey, _ := parseThreadKeyFromJID(chatJIDStr)
		return c.editIGMessage(threadKey, messageID, newText)
	}
	e2eeClient := c.snapshotE2EEClient()
	if e2eeClient == nil || !e2eeClient.IsConnected() {
		return ErrE2EENotConnected
	}

	chatJID, err := parseJID(chatJIDStr)
	if err != nil {
		return err
	}

	msgKey := e2eeClient.BuildMessageKey(chatJID, waTypes.EmptyJID, messageID)
	ts := time.Now().UnixMilli()
	editMsg := &waConsumerApplication.ConsumerApplication{
		Payload: &waConsumerApplication.ConsumerApplication_Payload{
			Payload: &waConsumerApplication.ConsumerApplication_Payload_Content{
				Content: &waConsumerApplication.ConsumerApplication_Content{
					Content: &waConsumerApplication.ConsumerApplication_Content_EditMessage{
						EditMessage: &waConsumerApplication.ConsumerApplication_EditMessage{
							Key:         msgKey,
							Message:     &waCommon.MessageText{Text: &newText},
							TimestampMS: &ts,
						},
					},
				},
			},
		},
	}

	editID := strconv.FormatInt(time.Now().UnixNano(), 10)
	_, err = e2eeClient.SendFBMessage(c.ctx, chatJID, editMsg, nil, whatsmeow.SendRequestExtra{ID: editID})
	return err
}

// UnsendE2EEMessage unsends/deletes an E2EE message
func (c *Client) UnsendE2EEMessage(chatJIDStr, messageID string) error {
	if c.Platform == types.Instagram && c.IG != nil {
		if !c.IsE2EEConnected() {
			return ErrE2EENotConnected
		}
		threadKey, _ := parseThreadKeyFromJID(chatJIDStr)
		return c.unsendIGMessage(threadKey, messageID)
	}
	e2eeClient := c.snapshotE2EEClient()
	if e2eeClient == nil || !e2eeClient.IsConnected() {
		return ErrE2EENotConnected
	}

	chatJID, err := parseJID(chatJIDStr)
	if err != nil {
		return err
	}

	msgKey := e2eeClient.BuildMessageKey(chatJID, waTypes.EmptyJID, messageID)
	revokeMsg := &waConsumerApplication.ConsumerApplication{
		Payload: &waConsumerApplication.ConsumerApplication_Payload{
			Payload: &waConsumerApplication.ConsumerApplication_Payload_ApplicationData{
				ApplicationData: &waConsumerApplication.ConsumerApplication_ApplicationData{
					ApplicationContent: &waConsumerApplication.ConsumerApplication_ApplicationData_Revoke{
						Revoke: &waConsumerApplication.ConsumerApplication_RevokeMessage{Key: msgKey},
					},
				},
			},
		},
	}

	revokeID := strconv.FormatInt(time.Now().UnixNano(), 10)
	_, err = e2eeClient.SendFBMessage(c.ctx, chatJID, revokeMsg, nil, whatsmeow.SendRequestExtra{ID: revokeID})
	return err
}
