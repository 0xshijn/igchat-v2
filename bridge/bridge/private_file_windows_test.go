//go:build windows

package bridge

import (
	"os"
	"testing"
)

func TestProtectPrivateFileWindowsSucceedsOnTempFile(t *testing.T) {
	f, err := createPrivateTempFile(os.TempDir(), "igchat-priv-*", 0o600)
	if err != nil {
		t.Fatalf("createPrivateTempFile() error = %v", err)
	}
	name := f.Name()
	_ = f.Close()
	defer os.Remove(name)

	if err := protectPrivateFile(name, 0o600); err != nil {
		t.Fatalf("protectPrivateFile() error = %v", err)
	}
}

