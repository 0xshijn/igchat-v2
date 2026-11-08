//go:build !windows

package bridge

import (
	"os"
	"testing"
)

func TestProtectPrivateFileUnixSetsMode0600(t *testing.T) {
	f, err := createPrivateTempFile(os.TempDir(), "igchat-priv-*", 0o600)
	if err != nil {
		t.Fatalf("createPrivateTempFile() error = %v", err)
	}
	name := f.Name()
	_ = f.Close()
	defer os.Remove(name)

	info, err := os.Stat(name)
	if err != nil {
		t.Fatalf("Stat() error = %v", err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("mode = %o, want 0600", info.Mode().Perm())
	}
}

