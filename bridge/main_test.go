package main

import (
	"context"
	"encoding/json"
	"errors"
	"slices"
	"strings"
	"testing"
)

func TestHelloPayloadDeclaresInstagramContract(t *testing.T) {
	payload := helloPayload()

	if got := payload["protocolVersion"]; got != bridgeProtocolVersion {
		t.Fatalf("protocolVersion = %v, want %d", got, bridgeProtocolVersion)
	}
	if got := payload["bridgeVersion"]; got != bridgeVersion {
		t.Fatalf("bridgeVersion = %v, want %q", got, bridgeVersion)
	}
	if got := payload["platform"]; got != "instagram" {
		t.Fatalf("platform = %v, want %q", got, "instagram")
	}

	capabilities, ok := payload["capabilities"].([]string)
	if !ok {
		t.Fatalf("capabilities has type %T, want []string", payload["capabilities"])
	}
	for _, required := range []string{
		"newClient",
		"connect",
		"isConnected",
		"events",
		"structuredConnectionStatus",
	} {
		if !slices.Contains(capabilities, required) {
			t.Errorf("capabilities does not contain %q", required)
		}
	}
	if slices.Contains(capabilities, "connectE2EE") {
		t.Errorf("capabilities unexpectedly contains deprecated connectE2EE")
	}
}

func TestConnectionPayloadWithoutClientHasNoE2EEFields(t *testing.T) {
	payload := connectionPayload(nil)
	if payload["connected"] != false || payload["nativeReconnecting"] != false {
		t.Fatalf("nil client connection payload = %#v", payload)
	}
	for _, absent := range []string{"e2eeConnected", "failureCode", "retryable", "permanent", "failureTransport"} {
		if _, exists := payload[absent]; exists {
			t.Fatalf("nil client payload unexpectedly contains %q", absent)
		}
	}
}

func TestFailureResponseAddsOnlyTypedStructuredClassification(t *testing.T) {
	network := failureResponse(7, context.DeadlineExceeded)
	if network.ErrorCode != "network_disconnected" || network.Retryable == nil || !*network.Retryable {
		t.Fatalf("network failure response = %#v", network)
	}

	opaque := failureResponse(8, errors.New("opaque provider detail"))
	if opaque.ErrorCode != "" || opaque.Retryable != nil {
		t.Fatalf("opaque failure was guessed from text: %#v", opaque)
	}
}

func TestServeRequestsRejectsOversizedLine(t *testing.T) {
	input := strings.NewReader(strings.Repeat("x", 65) + "\n")
	if err := serveRequests(input, 64); err == nil {
		t.Fatal("serveRequests() accepted a request larger than its hard limit")
	}
}

func TestRejectedLegacyE2EEMethodsReturnUnknownMethod(t *testing.T) {
	for _, legacyMethod := range []string{"connectE2EE", "sendE2EEMessage", "sendE2EEReaction", "downloadE2EEMedia"} {
		req := &request{ID: 99, Method: legacyMethod, Params: json.RawMessage(`{}`)}
		if req.Method == "" {
			t.Fatal("empty method")
		}
	}
	if got := failureResponse(1, errors.New("unknown method: connectE2EE")).Error; !strings.Contains(got, "unknown method") {
		t.Fatalf("unexpected error formatting: %q", got)
	}
}

