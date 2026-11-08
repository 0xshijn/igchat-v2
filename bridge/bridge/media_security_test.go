package bridge

import (
	"os"
	"strings"
	"testing"
)

func TestValidateMediaURLRestrictsInstagramCDNHosts(t *testing.T) {
	allowed := []string{
		"https://scontent.cdninstagram.com/v/image.jpg",
		"https://www.instagram.com/direct_v2/media.jpg",
		"https://video.fbcdn.net/v/clip.mp4",
		"https://cdn.fbsbx.com/file.pdf",
	}
	for _, raw := range allowed {
		if _, err := validateMediaURL(raw); err != nil {
			t.Errorf("validateMediaURL(%q) failed: %v", raw, err)
		}
	}

	rejected := []string{
		"http://scontent.cdninstagram.com/v/image.jpg",
		"https://scontent.cdninstagram.com:8443/v/image.jpg",
		"https://evil.example.com/media.jpg",
		"https://www.facebook.com/photo.jpg",
		"https://www.messenger.com/photo.jpg",
	}
	for _, raw := range rejected {
		if _, err := validateMediaURL(raw); err == nil {
			t.Errorf("validateMediaURL(%q) unexpectedly succeeded", raw)
		}
	}
}

func TestBoundedMediaFileEnforcesMaxSize(t *testing.T) {
	f, err := createBoundedMediaTempFile(8)
	if err != nil {
		t.Fatalf("createBoundedMediaTempFile() error = %v", err)
	}
	name := f.Name()
	defer func() {
		_ = f.Close()
		_ = os.Remove(name)
	}()

	if _, err := f.Write([]byte("12345678")); err != nil {
		t.Fatalf("Write(8 bytes) error = %v", err)
	}
	if _, err := f.Write([]byte("9")); err == nil {
		t.Fatal("Write() exceeded 8-byte cap")
	}
	if _, err := f.ReadFrom(strings.NewReader("extra")); err == nil {
		t.Fatal("ReadFrom() exceeded 8-byte cap")
	}
}

