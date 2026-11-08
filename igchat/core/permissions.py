"""Private filesystem permissions and atomic JSON creation."""

from __future__ import annotations

import os
import secrets
import stat
import subprocess
from pathlib import Path

PRIVATE_FILE_ENV = "IGCHAT_PRIVATE_FILE"


def _win32_user_sid() -> str | None:
    if os.name != "nt":
        return None
    try:
        completed = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=True,
        )
    except Exception:
        return None
    line = completed.stdout.strip()
    if not line:
        return None
    parts = [segment.strip().strip('"') for segment in line.split(",")]
    if len(parts) >= 2 and parts[-1].startswith("S-1-"):
        return parts[-1]
    return None


def _apply_windows_private_acl(target: Path) -> None:
    sid = _win32_user_sid()
    if not sid:
        return
    try:
        subprocess.run(
            [
                "icacls",
                str(target),
                "/inheritance:r",
                "/grant:r",
                f"*{sid}:F",
                "*S-1-5-18:F",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except Exception as exc:
        raise PermissionError(
            f"Không khóa được ACL riêng tư cho {target.name}"
        ) from exc


def set_private_file_permissions(path: str | Path) -> None:
    """Restrict a credential or session file to owner-only permissions."""
    target = Path(path)
    if target.is_symlink() or not target.is_file():
        raise PermissionError(f"Đường dẫn riêng tư không hợp lệ: {target}")
    if os.name == "nt":
        _apply_windows_private_acl(target)
        return
    os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)


def require_private_file(path: str | Path) -> Path:
    """Ensure the target path is a regular file (never a symlink) and return it."""
    target = Path(path)
    if target.is_symlink():
        raise PermissionError(f"Từ chối đọc symbolic link: {target}")
    if not target.is_file():
        raise FileNotFoundError(f"Không tìm thấy tệp: {target}")
    return target


def create_private_json_file(path: str | Path, content: str) -> Path:
    """Write JSON content atomically with strict 0600 / private Windows ACL."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise PermissionError(f"Từ chối ghi đè symbolic link: {destination}")

    tmp_path = destination.with_name(f".{destination.name}.{secrets.token_hex(6)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    mode = 0o600
    try:
        fd = os.open(tmp_path, flags, mode)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        set_private_file_permissions(tmp_path)
        tmp_path.replace(destination)
        set_private_file_permissions(destination)
        return destination
    except BaseException:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
