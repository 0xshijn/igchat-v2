package bridge

import (
	"context"
	"crypto/x509"
	"errors"
	"net"
	"testing"

	"go.mau.fi/mautrix-meta/pkg/instameow"
	"go.mau.fi/mautrix-meta/pkg/messagix/dgw"
	"go.mau.fi/mautrix-meta/pkg/messagix/httpclient"
)

func TestClassifyConnectionErrorInstagramSentinels(t *testing.T) {
	cases := []struct {
		name      string
		err       error
		code      FailureCode
		retryable bool
		permanent bool
	}{
		{"cancelled", context.Canceled, FailureCancelled, false, false},
		{"deadline", context.DeadlineExceeded, FailureNetworkDisconnected, true, false},
		{"checkpoint", httpclient.ErrCheckpointRequired, FailureCheckpointRequired, false, true},
		{"challenge", httpclient.ErrChallengeRequired, FailureCheckpointRequired, false, true},
		{"token_invalidated", httpclient.ErrTokenInvalidated, FailureAuthFailed, false, true},
		{"user_id_missing", instameow.ErrUserIDMissing, FailureAuthFailed, false, true},
		{"main_stream_closed", instameow.ErrMainStreamClosed, FailureNetworkDisconnected, true, false},
		{"dgw_dial", dgw.ErrDial, FailureNetworkDisconnected, true, false},
		{"cert_unknown", x509.UnknownAuthorityError{}, FailureConfigInvalid, false, true},
		{"net_error", &net.DNSError{IsTimeout: true}, FailureNetworkDisconnected, true, false},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := ClassifyConnectionError(tc.err)
			if !got.Classified {
				t.Fatalf("expected error %T to be classified", tc.err)
			}
			if got.Code != tc.code || got.Retryable != tc.retryable || got.Permanent != tc.permanent {
				t.Fatalf("got %+v, want code=%s retryable=%v permanent=%v", got, tc.code, tc.retryable, tc.permanent)
			}
		})
	}

	if got := ClassifyConnectionError(errors.New("untyped error")); got.Classified {
		t.Fatalf("untyped error must not be classified by string: %+v", got)
	}
}

func TestPermanentFailureIsStickyAcrossTransientEvents(t *testing.T) {
	c := &Client{eventChan: make(chan *Event, 8)}
	c.emitConnectionFailure(permanentConnectionFailure(httpclient.ErrTokenInvalidated))
	c.emitConnectionFailure(transientConnectionFailure(context.DeadlineExceeded))

	status := c.ConnectionStatus()
	if !status.HasFailure || status.FailureCode != FailureAuthFailed || !status.Permanent || status.Retryable {
		t.Fatalf("permanent failure overwritten: %+v", status)
	}
}

