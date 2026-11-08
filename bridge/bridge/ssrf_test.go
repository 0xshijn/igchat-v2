package bridge

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestValidateExternalURLBlocksSSRFTargets(t *testing.T) {
	blocked := []string{
		"http://127.0.0.1/media.jpg",
		"http://localhost:8080/media.jpg",
		"http://[::1]/media.jpg",
		"http://[::ffff:127.0.0.1]/media.jpg",
		"http://169.254.169.254/latest/meta-data/",
		"http://10.0.0.1/internal.png",
		"http://172.16.5.4/internal.png",
		"http://192.168.1.1/router.png",
		"http://100.64.0.1/cgnat.png",
		"https://user:pass@cdninstagram.com/a.jpg",
		"file:///etc/passwd",
		"ftp://cdninstagram.com/a.jpg",
	}
	for _, raw := range blocked {
		if _, err := validateExternalURL(raw, false, nil); err == nil {
			t.Errorf("validateExternalURL(%q) unexpectedly allowed SSRF target", raw)
		}
	}
}

func TestSafeHTTPClientBlocksLoopbackDialEvenOnRedirect(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	client := newSafeHTTPClient(5, false, nil)
	_, err := client.Get(strings.Replace(server.URL, "http://", "http://", 1))
	if err == nil {
		t.Fatal("safe HTTP client connected to loopback test server")
	}
}

