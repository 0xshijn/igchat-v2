package bridge

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path"
	"strings"
	"time"

	"go.mau.fi/mautrix-meta/pkg/messagix/httpclient"
)

const (
	maxDownloadedMediaSize int64 = 100 * 1024 * 1024
	maxURLUploadMediaBytes int64 = 25 * 1024 * 1024
	maxAvatarDownloadBytes int64 = 10 * 1024 * 1024
)

var errDownloadedMediaTooLarge = errors.New("media exceeds the 100 MiB limit")

type boundedMediaFile struct {
	*os.File
	maxSize int64
}

func createBoundedMediaTempFile(maxSize int64) (*boundedMediaFile, error) {
	file, err := createPrivateTempFile(os.TempDir(), "igchat-media-*", 0o600)
	if err != nil {
		return nil, fmt.Errorf("create bounded media file: %w", err)
	}
	return &boundedMediaFile{File: file, maxSize: maxSize}, nil
}

func (file *boundedMediaFile) validateWrite(offset int64, length int) error {
	if offset < 0 || offset > file.maxSize || int64(length) > file.maxSize-offset {
		return errDownloadedMediaTooLarge
	}
	return nil
}

func (file *boundedMediaFile) Write(data []byte) (int, error) {
	offset, err := file.File.Seek(0, io.SeekCurrent)
	if err != nil {
		return 0, err
	}
	if err = file.validateWrite(offset, len(data)); err != nil {
		return 0, err
	}
	return file.File.Write(data)
}

func (file *boundedMediaFile) WriteString(data string) (int, error) {
	offset, err := file.File.Seek(0, io.SeekCurrent)
	if err != nil {
		return 0, err
	}
	if err = file.validateWrite(offset, len(data)); err != nil {
		return 0, err
	}
	return file.File.WriteString(data)
}

func (file *boundedMediaFile) WriteAt(data []byte, offset int64) (int, error) {
	if err := file.validateWrite(offset, len(data)); err != nil {
		return 0, err
	}
	return file.File.WriteAt(data, offset)
}

func (file *boundedMediaFile) ReadFrom(source io.Reader) (int64, error) {
	return io.Copy(struct{ io.Writer }{file}, source)
}

func (file *boundedMediaFile) Truncate(size int64) error {
	if size < 0 || size > file.maxSize {
		return errDownloadedMediaTooLarge
	}
	return file.File.Truncate(size)
}

// UploadMediaOptions configures RUpload media bytes to Instagram.
type UploadMediaOptions struct {
	ThreadID int64  `json:"threadId"`
	Filename string `json:"filename"`
	MimeType string `json:"mimeType"`
	Data     []byte `json:"data"`
	IsVoice  bool   `json:"isVoice"`
}

// UploadMediaResult holds the resulting Instagram media upload ID.
type UploadMediaResult struct {
	MediaID  int64  `json:"mediaId"`
	Filename string `json:"filename"`
}

// UploadMedia uploads media bytes to Instagram via `SendMercuryUploadRequest`.
func (c *Client) UploadMedia(opts *UploadMediaOptions) (*UploadMediaResult, error) {
	if c.IG == nil || c.IG.GetHTTP() == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	media := &httpclient.MercuryUploadMedia{
		Filename:    opts.Filename,
		MimeType:    opts.MimeType,
		MediaData:   opts.Data,
		IsVoiceClip: opts.IsVoice,
	}
	resp, err := c.IG.GetHTTP().SendMercuryUploadRequest(c.opContext(), opts.ThreadID, media)
	if err != nil {
		return nil, err
	}
	var mediaID int64
	if resp.Payload.RealMetadata != nil {
		mediaID = resp.Payload.RealMetadata.GetFbId()
	}
	return &UploadMediaResult{
		MediaID:  mediaID,
		Filename: opts.Filename,
	}, nil
}

// SendMediaOptions configures sending already-uploaded media IDs into a thread.
type SendMediaOptions struct {
	ThreadID  int64   `json:"threadId"`
	MediaIDs  []int64 `json:"mediaIds"`
	Caption   string  `json:"caption"`
	ReplyToID string  `json:"replyToId,omitempty"`
}

// SendMedia sends uploaded media IDs to an Instagram Direct thread.
func (c *Client) SendMedia(opts *SendMediaOptions) (*SendMessageResult, error) {
	return c.SendMessage(&SendMessageOptions{
		ThreadID:        opts.ThreadID,
		Text:            opts.Caption,
		AttachmentFbIds: opts.MediaIDs,
		ReplyToID:       opts.ReplyToID,
	})
}

// SendImageOptions configures uploading and sending an image.
type SendImageOptions struct {
	ThreadID  int64  `json:"threadId"`
	Data      []byte `json:"data"`
	Filename  string `json:"filename"`
	Caption   string `json:"caption"`
	ReplyToID string `json:"replyToId,omitempty"`
}

// SendImage uploads image bytes and sends them to an Instagram Direct thread.
func (c *Client) SendImage(opts *SendImageOptions) (*SendMessageResult, error) {
	mimeType := "image/jpeg"
	lower := strings.ToLower(opts.Filename)
	switch {
	case strings.HasSuffix(lower, ".png"):
		mimeType = "image/png"
	case strings.HasSuffix(lower, ".gif"):
		mimeType = "image/gif"
	case strings.HasSuffix(lower, ".webp"):
		mimeType = "image/webp"
	}
	filename := opts.Filename
	if filename == "" {
		filename = "image.jpg"
	}
	uploadResult, err := c.UploadMedia(&UploadMediaOptions{
		ThreadID: opts.ThreadID,
		Filename: filename,
		MimeType: mimeType,
		Data:     opts.Data,
		IsVoice:  false,
	})
	if err != nil {
		return nil, err
	}
	return c.SendMedia(&SendMediaOptions{
		ThreadID:  opts.ThreadID,
		MediaIDs:  []int64{uploadResult.MediaID},
		Caption:   opts.Caption,
		ReplyToID: opts.ReplyToID,
	})
}

// SendVideoOptions configures uploading and sending a video.
type SendVideoOptions struct {
	ThreadID  int64  `json:"threadId"`
	Data      []byte `json:"data"`
	Filename  string `json:"filename"`
	Caption   string `json:"caption"`
	ReplyToID string `json:"replyToId,omitempty"`
}

// SendVideo uploads video bytes and sends them to an Instagram Direct thread.
func (c *Client) SendVideo(opts *SendVideoOptions) (*SendMessageResult, error) {
	filename := opts.Filename
	if filename == "" {
		filename = "video.mp4"
	}
	uploadResult, err := c.UploadMedia(&UploadMediaOptions{
		ThreadID: opts.ThreadID,
		Filename: filename,
		MimeType: "video/mp4",
		Data:     opts.Data,
		IsVoice:  false,
	})
	if err != nil {
		return nil, err
	}
	return c.SendMedia(&SendMediaOptions{
		ThreadID:  opts.ThreadID,
		MediaIDs:  []int64{uploadResult.MediaID},
		Caption:   opts.Caption,
		ReplyToID: opts.ReplyToID,
	})
}

// SendVoiceOptions configures uploading and sending a voice clip.
type SendVoiceOptions struct {
	ThreadID  int64  `json:"threadId"`
	Data      []byte `json:"data"`
	Filename  string `json:"filename"`
	ReplyToID string `json:"replyToId,omitempty"`
}

// SendVoice uploads audio bytes as an Instagram voice note.
func (c *Client) SendVoice(opts *SendVoiceOptions) (*SendMessageResult, error) {
	filename := opts.Filename
	if filename == "" {
		filename = "voice.mp4"
	}
	mimeType := "audio/mp4"
	lower := strings.ToLower(filename)
	switch {
	case strings.HasSuffix(lower, ".mp3"):
		mimeType = "audio/mpeg"
	case strings.HasSuffix(lower, ".ogg"):
		mimeType = "audio/ogg"
	case strings.HasSuffix(lower, ".wav"):
		mimeType = "audio/wav"
	}
	uploadResult, err := c.UploadMedia(&UploadMediaOptions{
		ThreadID: opts.ThreadID,
		Filename: filename,
		MimeType: mimeType,
		Data:     opts.Data,
		IsVoice:  true,
	})
	if err != nil {
		return nil, err
	}
	return c.SendMedia(&SendMediaOptions{
		ThreadID:  opts.ThreadID,
		MediaIDs:  []int64{uploadResult.MediaID},
		ReplyToID: opts.ReplyToID,
	})
}

// SendFileOptions configures uploading and sending an arbitrary file.
type SendFileOptions struct {
	ThreadID  int64  `json:"threadId"`
	Data      []byte `json:"data"`
	Filename  string `json:"filename"`
	MimeType  string `json:"mimeType"`
	Caption   string `json:"caption"`
	ReplyToID string `json:"replyToId,omitempty"`
}

// SendFile uploads file bytes and sends them into a thread.
func (c *Client) SendFile(opts *SendFileOptions) (*SendMessageResult, error) {
	uploadResult, err := c.UploadMedia(&UploadMediaOptions{
		ThreadID: opts.ThreadID,
		Filename: opts.Filename,
		MimeType: opts.MimeType,
		Data:     opts.Data,
		IsVoice:  false,
	})
	if err != nil {
		return nil, err
	}
	return c.SendMedia(&SendMediaOptions{
		ThreadID:  opts.ThreadID,
		MediaIDs:  []int64{uploadResult.MediaID},
		Caption:   opts.Caption,
		ReplyToID: opts.ReplyToID,
	})
}

// DownloadMedia downloads an Instagram CDN attachment URL over SSRF-protected HTTPS.
func (c *Client) DownloadMedia(rawURL string) ([]byte, error) {
	parsed, err := validateMediaURL(rawURL)
	if err != nil {
		return nil, err
	}
	client := newSafeHTTPClient(30*time.Second, true, allowedInstagramMediaHosts)
	req, err := http.NewRequestWithContext(c.opContext(), http.MethodGet, parsed.String(), nil)
	if err != nil {
		return nil, err
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode < http.StatusOK || resp.StatusCode >= http.StatusMultipleChoices {
		return nil, fmt.Errorf("media download returned HTTP %d", resp.StatusCode)
	}
	if resp.ContentLength > maxDownloadedMediaSize {
		return nil, errDownloadedMediaTooLarge
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxDownloadedMediaSize+1))
	if err != nil {
		return nil, err
	}
	if int64(len(data)) > maxDownloadedMediaSize {
		return nil, errDownloadedMediaTooLarge
	}
	return data, nil
}

// SendMediaFromURL downloads media from an SSRF-validated public HTTP(S) URL and sends it.
func (c *Client) SendMediaFromURL(threadID int64, mediaURL, filename, mimeType, replyToID string, isVoice bool) (*SendMessageResult, error) {
	if c.IG == nil {
		return nil, errors.New("instagram client is not initialized")
	}
	parsedURL, err := validateExternalURL(mediaURL, false, nil)
	if err != nil {
		return nil, err
	}
	reqCtx, cancel := context.WithTimeout(c.opContext(), 30*time.Second)
	defer cancel()
	httpReq, err := http.NewRequestWithContext(reqCtx, http.MethodGet, parsedURL.String(), nil)
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
	client := newSafeHTTPClient(30*time.Second, false, nil)
	resp, err := client.Do(httpReq)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("failed to download media: HTTP %d", resp.StatusCode)
	}
	if resp.ContentLength > maxURLUploadMediaBytes {
		return nil, errors.New("media exceeds 25 MiB limit")
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxURLUploadMediaBytes+1))
	if err != nil {
		return nil, err
	}
	if len(data) == 0 {
		return nil, errors.New("downloaded media is empty")
	}
	if int64(len(data)) > maxURLUploadMediaBytes {
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
	uploaded, err := c.UploadMedia(&UploadMediaOptions{
		ThreadID: threadID,
		Filename: filename,
		MimeType: mimeType,
		Data:     data,
		IsVoice:  isVoice,
	})
	if err != nil {
		return nil, err
	}
	return c.SendMessage(&SendMessageOptions{
		ThreadID:        threadID,
		AttachmentFbIds: []int64{uploaded.MediaID},
		ReplyToID:       replyToID,
	})
}

func (c *Client) editIGGroupAvatar(threadKey int64, avatarData []byte) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	ctx := c.opContext()
	ids, err := c.resolveIGThreadIDs(ctx, threadKey)
	if err != nil {
		return err
	}
	if len(avatarData) == 0 {
		return c.IG.RemoveGroupAvatar(ctx, ids.LongID)
	}
	return c.IG.EditGroupAvatar(ctx, ids.LongID, avatarData)
}

// EditGroupAvatarFromURL updates or clears a group thread avatar using a public image URL.
func (c *Client) EditGroupAvatarFromURL(threadID int64, imageURL string) error {
	if c.IG == nil {
		return errors.New("instagram client is not initialized")
	}
	trimmed := strings.TrimSpace(imageURL)
	if trimmed == "" || strings.EqualFold(trimmed, "clear") || strings.EqualFold(trimmed, "remove") {
		return c.editIGGroupAvatar(threadID, nil)
	}
	parsedURL, err := validateExternalURL(trimmed, false, nil)
	if err != nil {
		return err
	}
	reqCtx, cancel := context.WithTimeout(c.opContext(), 20*time.Second)
	defer cancel()
	httpReq, err := http.NewRequestWithContext(reqCtx, http.MethodGet, parsedURL.String(), nil)
	if err != nil {
		return err
	}
	httpReq.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
	client := newSafeHTTPClient(20*time.Second, false, nil)
	resp, err := client.Do(httpReq)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("failed to download avatar image: HTTP %d", resp.StatusCode)
	}
	if resp.ContentLength > maxAvatarDownloadBytes {
		return errors.New("invalid avatar image size")
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxAvatarDownloadBytes+1))
	if err != nil {
		return err
	}
	if len(data) == 0 || int64(len(data)) > maxAvatarDownloadBytes {
		return errors.New("invalid avatar image size")
	}
	return c.editIGGroupAvatar(threadID, data)
}

