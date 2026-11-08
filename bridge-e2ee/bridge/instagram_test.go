package bridge

import (
	"testing"

	"go.mau.fi/mautrix-meta/pkg/instameow/slidetypes"
)

func TestExtractIGAttachments(t *testing.T) {
	imgAtts := extractIGAttachments(&slidetypes.MessageContentImage{
		Attachments: []*slidetypes.Attachment{
			{
				AttachmentCDNURL: "https://example.com/photo.jpg",
				PreviewCDNURL:    "https://example.com/photo_thumb.jpg",
				PreviewWidth:     800,
				PreviewHeight:    600,
			},
		},
	})
	if len(imgAtts) != 1 || imgAtts[0].Type != "image" || imgAtts[0].URL != "https://example.com/photo.jpg" {
		t.Fatalf("unexpected image attachments: %+v", imgAtts)
	}

	audioAtts := extractIGAttachments(&slidetypes.MessageContentAudio{
		AudioAttachments: []*slidetypes.AudioAttachment{
			{
				AttachmentCDNURL:   "https://example.com/voice.mp4",
				PlayableDurationMS: 4200,
			},
		},
	})
	if len(audioAtts) != 1 || audioAtts[0].Type != "audio" || audioAtts[0].Duration != 4 {
		t.Fatalf("unexpected audio attachments: %+v", audioAtts)
	}

	stickerAtts := extractIGAttachments(&slidetypes.MessageContentSticker{
		PreviewURL:    "https://example.com/sticker.webp",
		PreviewWidth:  256,
		PreviewHeight: 256,
		AltText:       "Cat Sticker",
	})
	if len(stickerAtts) != 1 || stickerAtts[0].Type != "sticker" || stickerAtts[0].URL != "https://example.com/sticker.webp" {
		t.Fatalf("unexpected sticker attachments: %+v", stickerAtts)
	}
}

func TestCacheIGThreadInfoAndResolveKey(t *testing.T) {
	c := &Client{
		threadCache: make(map[int64]*Thread),
	}
	info := &slidetypes.ThreadInfo{
		ID:          "17864880735231976",
		ThreadID:    "340282366841710301244276039898312318952",
		ThreadKey:   17846530179231976,
		ThreadTitle: "Lê Phước Toàn",
	}
	thread := c.cacheIGThreadInfo(info)
	if thread == nil || thread.ID != 17846530179231976 {
		t.Fatalf("unexpected cached thread: %+v", thread)
	}
	if got := c.resolveIGThreadKey("17864880735231976"); got != 17846530179231976 {
		t.Fatalf("expected resolved thread key 17846530179231976, got %d", got)
	}
	if got, err := parseThreadKeyFromJID("17846530179231976@msgr"); err != nil || got != 17846530179231976 {
		t.Fatalf("unexpected parsed thread key: %d, err=%v", got, err)
	}
	mid, code := extractShortcodeFromInput("https://www.instagram.com/reel/C8abc123/")
	if code != "C8abc123" || mid == "" {
		t.Fatalf("unexpected shortcode extraction: mid=%s, code=%s", mid, code)
	}

	c.handleIGDelta(nil, &slidetypes.Delta{
		ThreadIGID: "17864880735231976",
		Data: &slidetypes.UpdateThreadNameEvent{
			ThreadName: "Renamed Group",
		},
	})
	if c.threadCache[17846530179231976].Name != "Renamed Group" {
		t.Fatalf("expected thread name to be updated, got %s", c.threadCache[17846530179231976].Name)
	}

	adminMsg := &slidetypes.Message{
		Content: slidetypes.MessageContentWrapper{
			Content: &slidetypes.MessageContentAdminText{
				TextFragments: []slidetypes.TextFragment{
					{Plaintext: "Lê Phước Toàn "},
					{Plaintext: "pinned a message"},
				},
			},
		},
	}
	if txt := extractIGMessageText(adminMsg); txt != "Lê Phước Toàn pinned a message" {
		t.Fatalf("unexpected admin message text: %s", txt)
	}

	c.handleIGDelta(nil, &slidetypes.Delta{
		ThreadIGID: "17864880735231976",
		Data:       &slidetypes.DeleteThreadEvent{},
	})
	if _, exists := c.threadCache[17846530179231976]; exists {
		t.Fatalf("expected deleted thread to be removed from cache")
	}
}
