// Standalone E2EE bridge for fbchat-v2.
//
// Communicates with the Python parent process over stdin/stdout using
// line-delimited JSON. Single-client per process (Python spawns one).
//
// Protocol
// --------
// Request  (Python -> bridge): one JSON object per line:
//
//	{"id": <int>, "method": "<name>", "params": {...}}
//
// Response (bridge -> Python): one JSON object per line:
//
//	{"id": <int>, "ok": true,  "data": {...}}
//	{"id": <int>, "ok": false, "error": "..."}
//
// Async event (bridge -> Python): one JSON object per line, no id:
//
//	{"event": {"type": "<name>", "data": {...}, "timestamp": <ms>}}
//
// Methods: hello, newClient, connect, connectE2EE, isConnected, disconnect,
// sendMessage, sendReaction, sendE2EEMessage, sendE2EEReaction,
// sendImage, sendFile, sendE2EESticker, sendE2EEVideo, sendE2EEDocument.
//
// Build:
//
//	go mod tidy
//	go build -ldflags="-s -w" -o ../build/fbchat-bridge-e2ee.exe .
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"sync"

	"fbchat-bridge-e2ee/bridge"
)

type request struct {
	ID     uint64          `json:"id"`
	Method string          `json:"method"`
	Params json.RawMessage `json:"params"`
}

type response struct {
	ID        uint64      `json:"id"`
	OK        bool        `json:"ok"`
	Data      interface{} `json:"data,omitempty"`
	Error     string      `json:"error,omitempty"`
	ErrorCode string      `json:"errorCode,omitempty"`
	Retryable *bool       `json:"retryable,omitempty"`
}

type eventEnvelope struct {
	Event *bridge.Event `json:"event"`
}

const bridgeProtocolVersion = 1

const maxRPCRequestBytes = 150 * 1024 * 1024

// bridgeVersion is intentionally overridable with -ldflags
// "-X main.bridgeVersion=<version>" for release builds.
var bridgeVersion = "2.3.4"

var bridgeCapabilities = []string{
	"newClient",
	"connect",
	"connectE2EE",
	"isConnected",
	"events",
	"structuredConnectionStatus",
}

var (
	client   *bridge.Client
	stdoutMu sync.Mutex
)

func writeJSON(v interface{}) {
	stdoutMu.Lock()
	defer stdoutMu.Unlock()
	enc := json.NewEncoder(os.Stdout)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(v)
}

func ok(id uint64, data interface{}) {
	writeJSON(response{ID: id, OK: true, Data: data})
}

func failureResponse(id uint64, err error) response {
	resp := response{ID: id, OK: false, Error: err.Error()}
	classification := bridge.ClassifyConnectionError(err)
	if classification.Classified {
		retryable := classification.Retryable
		resp.ErrorCode = string(classification.Code)
		resp.Retryable = &retryable
	}
	return resp
}

func fail(id uint64, err error) {
	writeJSON(failureResponse(id, err))
}

func connectionPayload(c *bridge.Client) map[string]interface{} {
	payload := map[string]interface{}{
		"connected":          false,
		"e2eeConnected":      false,
		"nativeReconnecting": false,
	}
	if c == nil {
		return payload
	}
	payload["connected"] = c.IsConnected()
	payload["e2eeConnected"] = c.IsE2EEConnected()
	status := c.ConnectionStatus()
	payload["nativeReconnecting"] = status.NativeReconnecting
	if status.HasFailure {
		payload["failureCode"] = status.FailureCode
		payload["retryable"] = status.Retryable
		payload["permanent"] = status.Permanent
		payload["failureTransport"] = status.FailureTransport
	}
	return payload
}

func helloPayload() map[string]interface{} {
	return map[string]interface{}{
		"protocolVersion": bridgeProtocolVersion,
		"bridgeVersion":   bridgeVersion,
		"capabilities":    bridgeCapabilities,
	}
}

// pumpEvents copies events from the client to stdout asynchronously.
func pumpEvents(c *bridge.Client) {
	for evt := range c.Events() {
		if evt == nil {
			continue
		}
		writeJSON(eventEnvelope{Event: evt})
	}
}

func handle(req *request) {
	switch req.Method {
	case "hello":
		ok(req.ID, helloPayload())

	case "newClient":
		if client != nil {
			fail(req.ID, fmt.Errorf("client already created"))
			return
		}
		var cfg bridge.ClientConfig
		if err := json.Unmarshal(req.Params, &cfg); err != nil {
			fail(req.ID, err)
			return
		}
		c, err := bridge.NewClient(&cfg)
		if err != nil {
			fail(req.ID, err)
			return
		}
		client = c
		go pumpEvents(client)
		ok(req.ID, map[string]interface{}{"ready": true})

	case "connect":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		user, _, err := client.Connect()
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{
			"user": user,
		})

	case "connectE2EE":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		if err := client.ConnectE2EE(); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{})

	case "isConnected":
		ok(req.ID, connectionPayload(client))

	case "sendMessage":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var opts bridge.SendMessageOptions
		if err := json.Unmarshal(req.Params, &opts); err != nil {
			fail(req.ID, err)
			return
		}
		res, err := client.SendMessage(&opts)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, res)

	case "sendReaction":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			ThreadID  int64  `json:"threadId"`
			MessageID string `json:"messageId"`
			Emoji     string `json:"emoji"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.SendReaction(p.ThreadID, p.MessageID, p.Emoji); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{})

	case "sendImage":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var opts bridge.SendImageOptions
		if err := json.Unmarshal(req.Params, &opts); err != nil {
			fail(req.ID, err)
			return
		}
		res, err := client.SendImage(&opts)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, res)

	case "sendFile":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var opts bridge.SendFileOptions
		if err := json.Unmarshal(req.Params, &opts); err != nil {
			fail(req.ID, err)
			return
		}
		res, err := client.SendFile(&opts)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, res)

	case "sendE2EEMessage":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			ChatJID          string  `json:"chatJid"`
			Text             string  `json:"text"`
			ReplyToID        string  `json:"replyToId,omitempty"`
			ReplyToSenderJID string  `json:"replyToSenderJid,omitempty"`
			MentionIDs       []int64 `json:"mentionIds,omitempty"`
			MentionOffsets   []int   `json:"mentionOffsets,omitempty"`
			MentionLengths   []int   `json:"mentionLengths,omitempty"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		res, err := client.SendMessage(&bridge.SendMessageOptions{
			Text:                 p.Text,
			IsE2EE:               true,
			E2EEChatJID:          p.ChatJID,
			E2EEReplyToID:        p.ReplyToID,
			E2EEReplyToSenderJID: p.ReplyToSenderJID,
			MentionIDs:           p.MentionIDs,
			MentionOffsets:       p.MentionOffsets,
			MentionLengths:       p.MentionLengths,
		})
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, res)

	case "sendE2EEReaction":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			ChatJID   string `json:"chatJid"`
			MessageID string `json:"messageId"`
			SenderJID string `json:"senderJid"`
			Emoji     string `json:"emoji"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.SendE2EEReaction(p.ChatJID, p.MessageID, p.SenderJID, p.Emoji); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{})

	case "sendE2EESticker":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var opts bridge.SendE2EEStickerOptions
		if err := json.Unmarshal(req.Params, &opts); err != nil {
			fail(req.ID, err)
			return
		}
		res, err := client.SendE2EESticker(&opts)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, res)

	case "sendE2EEVideo":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var opts bridge.SendE2EEVideoOptions
		if err := json.Unmarshal(req.Params, &opts); err != nil {
			fail(req.ID, err)
			return
		}
		res, err := client.SendE2EEVideo(&opts)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, res)

	case "sendE2EEDocument":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var opts bridge.SendE2EEDocumentOptions
		if err := json.Unmarshal(req.Params, &opts); err != nil {
			fail(req.ID, err)
			return
		}
		res, err := client.SendE2EEDocument(&opts)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, res)

	case "editMessage":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			MessageID string `json:"messageId"`
			NewText   string `json:"newText"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.EditMessage(p.MessageID, p.NewText); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{})

	case "unsendMessage":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			MessageID string `json:"messageId"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.UnsendMessage(p.MessageID); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{})

	case "editE2EEMessage":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			ChatJID   string `json:"chatJid"`
			MessageID string `json:"messageId"`
			NewText   string `json:"newText"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.EditE2EEMessage(p.ChatJID, p.MessageID, p.NewText); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{})

	case "unsendE2EEMessage":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			ChatJID   string `json:"chatJid"`
			MessageID string `json:"messageId"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.UnsendE2EEMessage(p.ChatJID, p.MessageID); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{})

	case "sendTypingIndicator":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			ThreadID   int64 `json:"threadId"`
			IsTyping   bool  `json:"isTyping"`
			IsGroup    bool  `json:"isGroup"`
			ThreadType int64 `json:"threadType"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.SendTypingIndicator(p.ThreadID, p.IsTyping, p.IsGroup, p.ThreadType); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{})

	case "markRead":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			ThreadID    int64 `json:"threadId"`
			WatermarkTs int64 `json:"watermarkTs"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.MarkRead(p.ThreadID, p.WatermarkTs); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{})

	case "sendE2EETyping":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			ChatJID  string `json:"chatJid"`
			IsTyping bool   `json:"isTyping"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.SendE2EETyping(p.ChatJID, p.IsTyping); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{})

	case "sendE2EEAudio":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var opts bridge.SendE2EEAudioOptions
		if err := json.Unmarshal(req.Params, &opts); err != nil {
			fail(req.ID, err)
			return
		}
		res, err := client.SendE2EEAudio(&opts)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, res)

	case "sendE2EEImage":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var opts bridge.SendE2EEImageOptions
		if err := json.Unmarshal(req.Params, &opts); err != nil {
			fail(req.ID, err)
			return
		}
		res, err := client.SendE2EEImage(&opts)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, res)

	case "downloadMedia":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			URL string `json:"url"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		data, err := client.DownloadMedia(p.URL)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{
			"data": data,
		})

	case "downloadE2EEMedia":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var opts bridge.DownloadE2EEMediaOptions
		if err := json.Unmarshal(req.Params, &opts); err != nil {
			fail(req.ID, err)
			return
		}
		res, err := client.DownloadE2EEMedia(&opts)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, res)

	case "pinMessage":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			ThreadID  int64  `json:"threadId"`
			MessageID string `json:"messageId"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.PinMessage(p.ThreadID, p.MessageID); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{})

	case "unpinMessage":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			ThreadID  int64  `json:"threadId"`
			MessageID string `json:"messageId"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.UnpinMessage(p.ThreadID, p.MessageID); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{})

	case "pinThread":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			ThreadID int64 `json:"threadId"`
			Pin      bool  `json:"pin"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.PinThread(p.ThreadID, p.Pin); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{})

	case "muteThread":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var opts bridge.MuteThreadOptions
		if err := json.Unmarshal(req.Params, &opts); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.MuteThread(&opts); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{})

	case "renameThread":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var opts bridge.RenameThreadOptions
		if err := json.Unmarshal(req.Params, &opts); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.RenameThread(&opts); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{})

	case "deleteThread":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var opts bridge.DeleteThreadOptions
		if err := json.Unmarshal(req.Params, &opts); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.DeleteThread(&opts); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{})

	case "acceptMessageRequest":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			ThreadID int64 `json:"threadId"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.AcceptMessageRequest(p.ThreadID); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{})

	case "searchUsers":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var opts bridge.SearchUsersOptions
		if err := json.Unmarshal(req.Params, &opts); err != nil {
			fail(req.ID, err)
			return
		}
		users, err := client.SearchUsers(&opts)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{"users": users})

	case "getUserInfo":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var opts bridge.GetUserInfoOptions
		if err := json.Unmarshal(req.Params, &opts); err != nil {
			fail(req.ID, err)
			return
		}
		info, err := client.GetUserInfo(&opts)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, info)

	case "getInbox":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		threads, err := client.GetInbox()
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{"threads": threads})

	case "getThreadInfo":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			ThreadID     int64 `json:"threadId"`
			MessageLimit int   `json:"messageLimit,omitempty"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		detail, err := client.GetThreadInfo(p.ThreadID, p.MessageLimit)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, detail)

	case "getMessageRequests":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		threads, err := client.GetMessageRequests()
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{"threads": threads})

	case "sendMediaFromURL":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			ThreadID  int64  `json:"threadId"`
			URL       string `json:"url"`
			Filename  string `json:"filename,omitempty"`
			MimeType  string `json:"mimeType,omitempty"`
			ReplyToID string `json:"replyToId,omitempty"`
			IsVoice   bool   `json:"isVoice,omitempty"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		res, err := client.SendMediaFromURL(p.ThreadID, p.URL, p.Filename, p.MimeType, p.ReplyToID, p.IsVoice)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, res)

	case "editGroupAvatar":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			ThreadID int64  `json:"threadId"`
			ImageURL string `json:"imageUrl"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.EditGroupAvatarFromURL(p.ThreadID, p.ImageURL); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{})

	case "forwardMessage":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			SourceThreadID int64  `json:"sourceThreadId"`
			TargetThreadID int64  `json:"targetThreadId"`
			MessageID      string `json:"messageId,omitempty"`
			Text           string `json:"text,omitempty"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		res, err := client.ForwardThreadMessage(p.SourceThreadID, p.TargetThreadID, p.MessageID, p.Text)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, res)

	case "getWebProfile":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			Identifier string `json:"identifier"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		prof, err := client.GetWebProfile(p.Identifier)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, prof)

	case "fetchStories":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			Identifier string `json:"identifier"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		stories, err := client.FetchStories(p.Identifier)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, stories)

	case "createGroup":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			UserIDs []int64 `json:"userIds"`
			Title   string  `json:"title,omitempty"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		thread, err := client.CreateGroup(p.UserIDs, p.Title)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, thread)

	case "addGroupMembers":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			ThreadID int64   `json:"threadId"`
			UserIDs  []int64 `json:"userIds"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.AddGroupMembers(p.ThreadID, p.UserIDs); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{})

	case "removeGroupMember":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			ThreadID int64 `json:"threadId"`
			UserID   int64 `json:"userId"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.RemoveGroupMember(p.ThreadID, p.UserID); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{})

	case "modifyGroupAdmins":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			ThreadID int64   `json:"threadId"`
			UserIDs  []int64 `json:"userIds"`
			Promote  bool    `json:"promote"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.ModifyGroupAdmins(p.ThreadID, p.UserIDs, p.Promote); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{})

	case "leaveGroup":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			ThreadID int64 `json:"threadId"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.LeaveGroup(p.ThreadID); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{})

	case "setUserBlocked":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			UserID  string `json:"userId"`
			Blocked bool   `json:"blocked"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.SetUserBlocked(p.UserID, p.Blocked); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]interface{}{})

	case "fetchMedia":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			Input string `json:"input"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		info, err := client.FetchMedia(p.Input)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, info)

	case "paginateInbox":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			Cursor string `json:"cursor"`
			Folder string `json:"folder"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		res, err := client.PaginateInbox(p.Cursor, p.Folder)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, res)

	case "paginateMessages":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		var p struct {
			ThreadID int64  `json:"threadId"`
			Cursor   string `json:"cursor"`
			Limit    int    `json:"limit"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		res, err := client.PaginateMessages(p.ThreadID, p.Cursor, p.Limit)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, res)

	case "getUnreadCount":
		if client == nil {
			fail(req.ID, fmt.Errorf("client not initialised"))
			return
		}
		res, err := client.GetUnreadCount()
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, res)

	case "disconnect":
		if client != nil {
			client.Disconnect()
			client = nil
		}
		ok(req.ID, map[string]interface{}{})

	default:
		fail(req.ID, fmt.Errorf("unknown method: %s", req.Method))
	}
}

func serveRequests(input io.Reader, maxRequestBytes int) error {
	if maxRequestBytes <= 0 {
		return fmt.Errorf("max request size must be positive")
	}
	initialBufferSize := 64 * 1024
	if maxRequestBytes < initialBufferSize {
		initialBufferSize = maxRequestBytes
	}
	scanner := bufio.NewScanner(input)
	scanner.Buffer(make([]byte, initialBufferSize), maxRequestBytes)
	for scanner.Scan() {
		var req request
		if err := json.Unmarshal(scanner.Bytes(), &req); err != nil {
			fail(0, fmt.Errorf("invalid json: %w", err))
			continue
		}
		handle(&req)
	}
	return scanner.Err()
}

func disconnectClient() {
	if client == nil {
		return
	}
	client.Disconnect()
	client = nil
}

func main() {
	defer disconnectClient()
	if err := serveRequests(os.Stdin, maxRPCRequestBytes); err != nil {
		fail(0, fmt.Errorf("stdin request exceeds the 150 MiB limit or could not be read: %w", err))
	}
}
