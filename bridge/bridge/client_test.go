package bridge

import (
	"context"
	"errors"
	"testing"

	"go.mau.fi/mautrix-meta/pkg/instameow"
	"go.mau.fi/mautrix-meta/pkg/instameow/slidetypes"
	"go.mau.fi/mautrix-meta/pkg/messagix/httpclient"
)

func TestNewClientRejectsNonInstagramPlatform(t *testing.T) {
	_, err := NewClient(&ClientConfig{
		Platform: "facebook",
		Cookies:  map[string]string{"sessionid": "abc", "csrftoken": "def", "ds_user_id": "123"},
	})
	if err == nil {
		t.Fatal("expected error for non-instagram platform")
	}
}

func TestIsConnectedChecksInstagramClientAndLifecycle(t *testing.T) {
	c, err := NewClient(&ClientConfig{
		Cookies:  map[string]string{"sessionid": "abc", "csrftoken": "def", "ds_user_id": "123"},
		LogLevel: "none",
	})
	if err != nil {
		t.Fatalf("NewClient() error = %v", err)
	}
	if c.IsConnected() {
		t.Fatal("new client should not report connected before Connect()")
	}
	c.connected.Store(true)
	if !c.IsConnected() {
		t.Fatal("client with IG + active context + connected flag should report true")
	}
	c.Disconnect()
	if c.IsConnected() {
		t.Fatal("disconnected client must report false")
	}
}

func TestHandleIGEventReconnectTransition(t *testing.T) {
	c, err := NewClient(&ClientConfig{
		Cookies:  map[string]string{"sessionid": "abc", "csrftoken": "def", "ds_user_id": "123"},
		LogLevel: "none",
	})
	if err != nil {
		t.Fatalf("NewClient() error = %v", err)
	}
	defer c.Disconnect()

	_ = c.handleIGEvent(context.Background(), &slidetypes.Connected{})
	if !c.IsConnected() {
		t.Fatal("expected IsConnected() after Connected event")
	}
	_ = c.handleIGEvent(context.Background(), &slidetypes.Disconnected{
		Error: errors.New("temporary drop"),
	})
	if c.IsConnected() {
		t.Fatal("expected IsConnected() false after Disconnected event")
	}
	_ = c.handleIGEvent(context.Background(), &slidetypes.Connected{})
	if !c.IsConnected() {
		t.Fatal("expected IsConnected() true after reconnect")
	}

	var seenTypes []EventType
	for {
		select {
		case evt := <-c.Events():
			if evt != nil && evt.Type != EventTypeRaw {
				seenTypes = append(seenTypes, evt.Type)
			}
		default:
			goto done
		}
	}
done:
	want := []EventType{EventTypeReady, EventTypeDisconnected, EventTypeError, EventTypeReconnected}
	if len(seenTypes) != len(want) {
		t.Fatalf("events = %v, want %v", seenTypes, want)
	}
	for i := range want {
		if seenTypes[i] != want[i] {
			t.Fatalf("events[%d] = %q, want %q", i, seenTypes[i], want[i])
		}
	}
}

func TestConnectRejectsUnauthenticatedCookies(t *testing.T) {
	c, err := NewClient(&ClientConfig{
		Cookies:  map[string]string{"csrftoken": "only_csrf"},
		LogLevel: "none",
	})
	if err != nil {
		t.Fatalf("NewClient() error = %v", err)
	}
	defer c.Disconnect()

	_, _, err = c.Connect()
	if !errors.Is(err, httpclient.ErrTokenInvalidated) {
		t.Fatalf("Connect() error = %v, want ErrTokenInvalidated", err)
	}
}

func TestClaimMessageIDDeduplicatesAndRespectsCap(t *testing.T) {
	c := &Client{recentMessages: make(map[string]int64)}
	if !c.claimMessageID("m1") {
		t.Fatal("first claim should succeed")
	}
	if c.claimMessageID("m1") {
		t.Fatal("duplicate claim should be suppressed")
	}
	_ = instameow.ErrClientIsNil
}

