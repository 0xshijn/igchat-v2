package bridge

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

func TestLogRedactionScrubsInstagramCookiesAndIDs(t *testing.T) {
	var out bytes.Buffer
	writer := newRedactingLogWriter(&out)

	raw := `{"level":"info","cookie":"sessionid=secret_sess; csrftoken=csrf_123; ds_user_id=987654321","database_id":"db1","user_id":"1234567890","url":"https://cdninstagram.com/v/t51.jpg?oh=secret&oe=123"}` + "\n"
	if _, err := writer.Write([]byte(raw)); err != nil {
		t.Fatalf("Write() error = %v", err)
	}

	line := out.String()
	for _, leak := range []string{"secret_sess", "csrf_123", "987654321", "1234567890", "oh=secret"} {
		if strings.Contains(line, leak) {
			t.Fatalf("redacted output leaked %q: %s", leak, line)
		}
	}

	var parsed map[string]any
	if err := json.Unmarshal([]byte(line), &parsed); err != nil {
		t.Fatalf("redacted output is invalid JSON: %v", err)
	}
	if parsed["database_id"] != "db1" {
		t.Fatalf("database_id was unexpectedly redacted: %v", parsed["database_id"])
	}
}

func TestLogRedactionDiscardsOversizedLineWithoutLeaking(t *testing.T) {
	var out bytes.Buffer
	writer := newRedactingLogWriter(&out)

	oversized := `{"secret":"` + strings.Repeat("A", maxRedactingLogLineBytes+1024) + "\"}\n"
	if _, err := writer.Write([]byte(oversized)); err != nil {
		t.Fatalf("Write() error = %v", err)
	}
	if strings.Contains(out.String(), "AAAA") {
		t.Fatal("oversized line leaked payload instead of discarding")
	}
	if out.String() != oversizedLogDiagnostic {
		t.Fatalf("got %q, want %q", out.String(), oversizedLogDiagnostic)
	}
}

