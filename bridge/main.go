// Standalone Instagram Direct Go bridge for igchat-v2.
//
// Communicates with the Python parent process over stdin/stdout using
// line-delimited JSON. Single client per bridge process.
//
// Build:
//
//	go mod tidy
//	go build -trimpath -ldflags="-s -w" -o ../build/igchat-bridge.exe .
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"sync"

	"igchat-bridge/bridge"
)

type request struct {
	ID     uint64          `json:"id"`
	Method string          `json:"method"`
	Params json.RawMessage `json:"params"`
}

type response struct {
	ID        uint64 `json:"id"`
	OK        bool   `json:"ok"`
	Data      any    `json:"data,omitempty"`
	Error     string `json:"error,omitempty"`
	ErrorCode string `json:"errorCode,omitempty"`
	Retryable *bool  `json:"retryable,omitempty"`
}

type eventEnvelope struct {
	Event *bridge.Event `json:"event"`
}

const bridgeProtocolVersion = 1

const maxRPCRequestBytes = 150 * 1024 * 1024

// bridgeVersion may be overridden with -ldflags "-X main.bridgeVersion=<version>".
var bridgeVersion = "3.0.0"

var bridgeCapabilities = []string{
	"newClient",
	"connect",
	"isConnected",
	"events",
	"structuredConnectionStatus",
}

var (
	client   *bridge.Client
	stdoutMu sync.Mutex
)

func writeJSON(v any) {
	stdoutMu.Lock()
	defer stdoutMu.Unlock()
	enc := json.NewEncoder(os.Stdout)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(v)
}

func ok(id uint64, data any) {
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

func connectionPayload(c *bridge.Client) map[string]any {
	payload := map[string]any{
		"connected":          false,
		"nativeReconnecting": false,
	}
	if c == nil {
		return payload
	}
	payload["connected"] = c.IsConnected()
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

func helloPayload() map[string]any {
	return map[string]any{
		"protocolVersion": bridgeProtocolVersion,
		"bridgeVersion":   bridgeVersion,
		"platform":        "instagram",
		"capabilities":    bridgeCapabilities,
	}
}

func pumpEvents(c *bridge.Client) {
	for evt := range c.Events() {
		if evt == nil {
			continue
		}
		writeJSON(eventEnvelope{Event: evt})
	}
}

func requireClient(id uint64) bool {
	if client == nil {
		fail(id, fmt.Errorf("client not initialized"))
		return false
	}
	return true
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
		ok(req.ID, map[string]any{"ready": true})

	case "connect":
		if !requireClient(req.ID) {
			return
		}
		user, initial, err := client.Connect()
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]any{
			"user":    user,
			"initial": initial,
		})

	case "isConnected":
		ok(req.ID, connectionPayload(client))

	case "sendMessage":
		if !requireClient(req.ID) {
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
		if !requireClient(req.ID) {
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
		ok(req.ID, map[string]any{})

	case "sendMedia":
		if !requireClient(req.ID) {
			return
		}
		var opts bridge.SendMediaOptions
		if err := json.Unmarshal(req.Params, &opts); err != nil {
			fail(req.ID, err)
			return
		}
		res, err := client.SendMedia(&opts)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, res)

	case "sendImage":
		if !requireClient(req.ID) {
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

	case "sendVideo":
		if !requireClient(req.ID) {
			return
		}
		var opts bridge.SendVideoOptions
		if err := json.Unmarshal(req.Params, &opts); err != nil {
			fail(req.ID, err)
			return
		}
		res, err := client.SendVideo(&opts)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, res)

	case "sendVoice":
		if !requireClient(req.ID) {
			return
		}
		var opts bridge.SendVoiceOptions
		if err := json.Unmarshal(req.Params, &opts); err != nil {
			fail(req.ID, err)
			return
		}
		res, err := client.SendVoice(&opts)
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, res)

	case "sendFile":
		if !requireClient(req.ID) {
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

	case "sendMediaFromURL":
		if !requireClient(req.ID) {
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

	case "downloadMedia":
		if !requireClient(req.ID) {
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
		ok(req.ID, map[string]any{"data": data})

	case "editMessage":
		if !requireClient(req.ID) {
			return
		}
		var p struct {
			ThreadID  int64  `json:"threadId,omitempty"`
			MessageID string `json:"messageId"`
			NewText   string `json:"newText"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.EditMessage(p.ThreadID, p.MessageID, p.NewText); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]any{})

	case "unsendMessage":
		if !requireClient(req.ID) {
			return
		}
		var p struct {
			ThreadID  int64  `json:"threadId,omitempty"`
			MessageID string `json:"messageId"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.UnsendMessage(p.ThreadID, p.MessageID); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]any{})

	case "sendTypingIndicator":
		if !requireClient(req.ID) {
			return
		}
		var p struct {
			ThreadID int64 `json:"threadId"`
			IsTyping bool  `json:"isTyping"`
		}
		if err := json.Unmarshal(req.Params, &p); err != nil {
			fail(req.ID, err)
			return
		}
		if err := client.SendTypingIndicator(p.ThreadID, p.IsTyping); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]any{})

	case "markRead":
		if !requireClient(req.ID) {
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
		ok(req.ID, map[string]any{})

	case "pinMessage":
		if !requireClient(req.ID) {
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
		if err := client.PinMessage(p.ThreadID, p.MessageID, true); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]any{})

	case "unpinMessage":
		if !requireClient(req.ID) {
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
		if err := client.PinMessage(p.ThreadID, p.MessageID, false); err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]any{})

	case "pinThread":
		if !requireClient(req.ID) {
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
		ok(req.ID, map[string]any{})

	case "muteThread":
		if !requireClient(req.ID) {
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
		ok(req.ID, map[string]any{})

	case "renameThread":
		if !requireClient(req.ID) {
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
		ok(req.ID, map[string]any{})

	case "deleteThread":
		if !requireClient(req.ID) {
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
		ok(req.ID, map[string]any{})

	case "acceptMessageRequest":
		if !requireClient(req.ID) {
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
		ok(req.ID, map[string]any{})

	case "searchUsers":
		if !requireClient(req.ID) {
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
		ok(req.ID, map[string]any{"users": users})

	case "getUserInfo":
		if !requireClient(req.ID) {
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
		if !requireClient(req.ID) {
			return
		}
		threads, err := client.GetInbox()
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]any{"threads": threads})

	case "getThreadInfo":
		if !requireClient(req.ID) {
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
		if !requireClient(req.ID) {
			return
		}
		threads, err := client.GetMessageRequests()
		if err != nil {
			fail(req.ID, err)
			return
		}
		ok(req.ID, map[string]any{"threads": threads})

	case "editGroupAvatar":
		if !requireClient(req.ID) {
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
		ok(req.ID, map[string]any{})

	case "forwardMessage":
		if !requireClient(req.ID) {
			return
		}
		var p bridge.ForwardMessageOptions
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
		if !requireClient(req.ID) {
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
		if !requireClient(req.ID) {
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
		if !requireClient(req.ID) {
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
		if !requireClient(req.ID) {
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
		ok(req.ID, map[string]any{})

	case "removeGroupMember":
		if !requireClient(req.ID) {
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
		ok(req.ID, map[string]any{})

	case "modifyGroupAdmins":
		if !requireClient(req.ID) {
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
		ok(req.ID, map[string]any{})

	case "leaveGroup":
		if !requireClient(req.ID) {
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
		ok(req.ID, map[string]any{})

	case "setUserBlocked":
		if !requireClient(req.ID) {
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
		ok(req.ID, map[string]any{})

	case "fetchMedia":
		if !requireClient(req.ID) {
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
		if !requireClient(req.ID) {
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
		if !requireClient(req.ID) {
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
		if !requireClient(req.ID) {
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
		ok(req.ID, map[string]any{})

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

