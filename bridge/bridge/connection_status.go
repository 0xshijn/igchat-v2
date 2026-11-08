package bridge

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"net"

	"go.mau.fi/mautrix-meta/pkg/instameow"
	"go.mau.fi/mautrix-meta/pkg/messagix/bloks"
	"go.mau.fi/mautrix-meta/pkg/messagix/dgw"
	"go.mau.fi/mautrix-meta/pkg/messagix/httpclient"
)

// FailureCode is a stable, non-sensitive machine-readable connection failure.
// It deliberately never includes provider payloads, credentials, IDs or raw
// upstream error strings.
type FailureCode string

const (
	FailureNetworkDisconnected FailureCode = "network_disconnected"
	FailureAuthFailed          FailureCode = "auth_failed"
	FailureCheckpointRequired  FailureCode = "checkpoint_required"
	FailureConfigInvalid       FailureCode = "config_invalid"
	FailureProtocolError       FailureCode = "protocol_error"
	FailureConnectionFailed    FailureCode = "connection_failed"
	FailureCancelled           FailureCode = "cancelled"
)

const connectionTransportInstagram = "instagram"

// ErrorClassification is safe to expose in the JSON-RPC envelope.
type ErrorClassification struct {
	Code       FailureCode
	Retryable  bool
	Permanent  bool
	Classified bool
}

// ConnectionStatus is the aggregate transport status returned by isConnected.
type ConnectionStatus struct {
	NativeReconnecting bool
	FailureCode        FailureCode
	Retryable          bool
	Permanent          bool
	FailureTransport   string
	HasFailure         bool
}

type transportFailureState struct {
	code               FailureCode
	retryable          bool
	permanent          bool
	nativeReconnecting bool
	active             bool
}

func classifiedFailure(code FailureCode, retryable, permanent bool) ErrorClassification {
	return ErrorClassification{
		Code:       code,
		Retryable:  retryable,
		Permanent:  permanent,
		Classified: true,
	}
}

// ClassifyConnectionError maps typed errors and sentinels to bounded non-sensitive codes.
func ClassifyConnectionError(err error) ErrorClassification {
	if err == nil {
		return ErrorClassification{}
	}
	if errors.Is(err, context.Canceled) {
		return classifiedFailure(FailureCancelled, false, false)
	}
	if errors.Is(err, context.DeadlineExceeded) {
		return classifiedFailure(FailureNetworkDisconnected, true, false)
	}
	if errors.Is(err, httpclient.ErrChallengeRequired) ||
		errors.Is(err, httpclient.ErrCheckpointRequired) {
		return classifiedFailure(FailureCheckpointRequired, false, true)
	}
	var checkpointError bloks.CheckpointError
	if errors.As(err, &checkpointError) {
		return classifiedFailure(FailureCheckpointRequired, false, true)
	}
	if errors.Is(err, httpclient.ErrTokenInvalidated) ||
		errors.Is(err, httpclient.ErrConsentRequired) ||
		errors.Is(err, httpclient.ErrAccountSuspended) ||
		errors.Is(err, instameow.ErrUserIDMissing) ||
		dgw.IsUnauthorized(err) {
		return classifiedFailure(FailureAuthFailed, false, true)
	}
	if errors.Is(err, instameow.ErrClientIsNil) {
		return classifiedFailure(FailureConfigInvalid, false, true)
	}
	if errors.Is(err, httpclient.ErrTooManyRedirects) ||
		errors.Is(err, httpclient.ErrVersionIDNotFound) ||
		errors.Is(err, instameow.ErrMailboxMissing) {
		return classifiedFailure(FailureProtocolError, false, true)
	}
	var certificateVerificationError *tls.CertificateVerificationError
	var unknownAuthorityError x509.UnknownAuthorityError
	var hostnameError x509.HostnameError
	var certificateInvalidError x509.CertificateInvalidError
	if errors.As(err, &certificateVerificationError) ||
		errors.As(err, &unknownAuthorityError) ||
		errors.As(err, &hostnameError) ||
		errors.As(err, &certificateInvalidError) {
		return classifiedFailure(FailureConfigInvalid, false, true)
	}
	var syntaxError *json.SyntaxError
	var typeError *json.UnmarshalTypeError
	if errors.As(err, &syntaxError) || errors.As(err, &typeError) {
		return classifiedFailure(FailureProtocolError, false, true)
	}
	if errors.Is(err, dgw.ErrDial) ||
		errors.Is(err, dgw.ErrPongTimeout) ||
		errors.Is(err, dgw.ErrAckTimeout) ||
		errors.Is(err, dgw.ErrReceiveTimeout) ||
		errors.Is(err, httpclient.ErrRequestFailed) ||
		errors.Is(err, httpclient.ErrResponseReadFailed) ||
		errors.Is(err, httpclient.ErrMaxRetriesReached) ||
		errors.Is(err, instameow.ErrMainStreamClosed) {
		return classifiedFailure(FailureNetworkDisconnected, true, false)
	}
	var networkError net.Error
	if errors.As(err, &networkError) {
		return classifiedFailure(FailureNetworkDisconnected, true, false)
	}
	return ErrorClassification{}
}

func transientConnectionFailure(err error) transportFailureState {
	classified := ClassifyConnectionError(err)
	if classified.Classified && (classified.Permanent || !classified.Retryable) {
		return transportFailureState{
			code:      classified.Code,
			retryable: classified.Retryable,
			permanent: true,
			active:    true,
		}
	}
	code := FailureNetworkDisconnected
	if classified.Classified {
		code = classified.Code
	}
	return transportFailureState{
		code:               code,
		retryable:          true,
		nativeReconnecting: true,
		active:             true,
	}
}

func permanentConnectionFailure(err error) transportFailureState {
	classified := ClassifyConnectionError(err)
	if !classified.Classified {
		classified = classifiedFailure(FailureConnectionFailed, false, true)
	}
	return transportFailureState{
		code:      classified.Code,
		retryable: classified.Retryable,
		permanent: classified.Permanent || !classified.Retryable,
		active:    true,
	}
}

func synchronousConnectionFailure(err error) transportFailureState {
	classified := ClassifyConnectionError(err)
	if !classified.Classified {
		classified = classifiedFailure(FailureConnectionFailed, false, true)
	}
	return transportFailureState{
		code:      classified.Code,
		retryable: classified.Retryable,
		permanent: classified.Permanent || !classified.Retryable,
		active:    true,
	}
}

func (c *Client) markTransportConnecting() {
	c.replaceTransportFailure(transportFailureState{
		code:               FailureNetworkDisconnected,
		retryable:          true,
		nativeReconnecting: true,
		active:             true,
	})
}

func (c *Client) setTransportFailure(failure transportFailureState) transportFailureState {
	c.connectionStatusMu.Lock()
	defer c.connectionStatusMu.Unlock()
	if c.transportFailure.active && c.transportFailure.permanent {
		return c.transportFailure
	}
	c.transportFailure = failure
	return failure
}

func (c *Client) replaceTransportFailure(failure transportFailureState) {
	c.connectionStatusMu.Lock()
	c.transportFailure = failure
	c.connectionStatusMu.Unlock()
}

func (c *Client) clearTransportFailure() {
	c.connectionStatusMu.Lock()
	c.transportFailure = transportFailureState{}
	c.connectionStatusMu.Unlock()
}

func (c *Client) ConnectionStatus() ConnectionStatus {
	if c == nil {
		return ConnectionStatus{}
	}
	c.connectionStatusMu.RLock()
	failure := c.transportFailure
	c.connectionStatusMu.RUnlock()

	status := ConnectionStatus{
		NativeReconnecting: failure.nativeReconnecting,
	}
	if !failure.active {
		return status
	}
	status.HasFailure = true
	status.FailureCode = failure.code
	status.Retryable = failure.retryable
	status.Permanent = failure.permanent
	status.FailureTransport = connectionTransportInstagram
	return status
}

func connectionFailureEventData(failure transportFailureState) map[string]any {
	return map[string]any{
		"transport":          connectionTransportInstagram,
		"nativeReconnecting": failure.nativeReconnecting,
		"failureCode":        failure.code,
		"retryable":          failure.retryable,
		"permanent":          failure.permanent,
	}
}

func safeConnectionFailureMessage(failure transportFailureState) string {
	switch failure.code {
	case FailureAuthFailed:
		return "Instagram authentication failed"
	case FailureCheckpointRequired:
		return "Instagram account verification is required"
	case FailureProtocolError:
		return "Instagram protocol is incompatible"
	case FailureConfigInvalid:
		return "Instagram configuration is invalid"
	case FailureCancelled:
		return "Instagram connection was cancelled"
	default:
		return "Instagram connection is unavailable"
	}
}

func (c *Client) emitConnectionFailure(failure transportFailureState) {
	failure = c.setTransportFailure(failure)
	c.emitEvent(EventTypeDisconnected, connectionFailureEventData(failure))
	code := 0
	if failure.permanent {
		code = 1
	}
	c.emitEvent(EventTypeError, &ErrorEvent{
		Message: safeConnectionFailureMessage(failure),
		Code:    code,
	})
}

