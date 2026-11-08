"""Unit tests for scripts.release_artifacts."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.release_artifacts import (
    read_project_version,
    render_checksum_module,
    validate_release_tag,
    verify_manifest,
)


def test_read_project_version_and_tag(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "igchat-v2"\nversion = "3.0.0"\n',
        encoding="utf-8",
    )
    ver = read_project_version(pyproject)
    assert ver == "3.0.0"

    validate_release_tag("v3.0.0", "3.0.0")
    with pytest.raises(RuntimeError):
        validate_release_tag("v2.3.4", "3.0.0")


def test_render_and_verify_manifest(tmp_path: Path) -> None:
    digests = {
        "igchat-bridge-linux-amd64": "a" * 64,
        "igchat-bridge-windows-amd64.exe": "b" * 64,
    }
    rendered = render_checksum_module("3.0.0", digests)
    assert "BRIDGE_RELEASE_VERSION: str | None = '3.0.0'" in rendered

    manifest_file = tmp_path / "manifest.sha256"
    manifest_file.write_text(
        f"{'a'*64}  igchat-bridge-linux-amd64\n{'b'*64}  igchat-bridge-windows-amd64.exe\n",
        encoding="ascii",
    )
    verify_manifest(manifest_file, digests)
