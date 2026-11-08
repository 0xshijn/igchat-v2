"""Verify the wheel/sdist layout and documented public API of igchat_v2."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib
import io
import stat
import sys
import tarfile
import unicodedata
import zipfile
from email.parser import Parser
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath

DISTIBUTION_NAME = "igchat-v2"
EXPECTED_VERSION = "3.0.0"
PACKAGE_NAMES = ("igchat_v2",)
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PACKAGE_DIR = REPO_ROOT / "src" / "igchat_v2"


def discover_canonical_members() -> frozenset[str]:
    members: set[str] = set()
    for file_path in SRC_PACKAGE_DIR.rglob("*"):
        if not file_path.is_file():
            continue
        rel = file_path.relative_to(REPO_ROOT / "src")
        if "__pycache__" in rel.parts or rel.suffix == ".pyc":
            continue
        members.add(rel.as_posix())
    return frozenset(members)


REQUIRED_WHEEL_MEMBERS: frozenset[str] = discover_canonical_members()
WHEEL_DIST_INFO_ROOT = f"igchat_v2-{EXPECTED_VERSION}.dist-info"
ALLOWED_WHEEL_MEMBERS = REQUIRED_WHEEL_MEMBERS | {
    f"{WHEEL_DIST_INFO_ROOT}/METADATA",
    f"{WHEEL_DIST_INFO_ROOT}/WHEEL",
    f"{WHEEL_DIST_INFO_ROOT}/RECORD",
    f"{WHEEL_DIST_INFO_ROOT}/licenses/LICENSE",
}
EXPECTED_SDIST_ROOT = f"igchat_v2-{EXPECTED_VERSION}"
ALLOWED_SDIST_FILES = frozenset(
    {
        ".gitignore",
        "CHANGELOG.md",
        "LICENSE",
        "README.md",
        "README_EN.md",
        "pyproject.toml",
        "PKG-INFO",
        *(f"src/{member}" for member in REQUIRED_WHEEL_MEMBERS),
    }
)


def _validate_archive_path(name: str, *, artifact: str) -> PurePosixPath:
    if "\\" in name:
        raise RuntimeError(f"{artifact} chứa đường dẫn dùng dấu gạch chéo ngược")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError(f"{artifact} chứa đường dẫn không an toàn: {name!r}")
    raw_name = name[:-1] if name.endswith("/") else name
    if path.as_posix() != raw_name:
        raise RuntimeError(f"{artifact} chứa đường dẫn không canonical: {name!r}")
    return path


def _reject_path_collisions(names: list[str], *, artifact: str) -> None:
    seen: dict[str, str] = {}
    for name in names:
        normalized = unicodedata.normalize("NFC", name.rstrip("/")).casefold()
        previous = seen.get(normalized)
        if previous is not None:
            raise RuntimeError(
                f"{artifact} chứa đường dẫn trùng Unicode/case: "
                f"{previous!r} và {name!r}"
            )
        seen[normalized] = name


def _allowed_directories(files: frozenset[str]) -> frozenset[str]:
    directories: set[str] = set()
    for name in files:
        parent = PurePosixPath(name).parent
        while parent != PurePosixPath("."):
            directories.add(parent.as_posix())
            parent = parent.parent
    return frozenset(directories)


def _record_digest(payload: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest())
    return "sha256=" + digest.rstrip(b"=").decode("ascii")


def _verify_wheel_record(archive: zipfile.ZipFile, members: set[str]) -> None:
    record_path = f"{WHEEL_DIST_INFO_ROOT}/RECORD"
    record_text = archive.read(record_path).decode("utf-8", errors="strict")
    rows = list(csv.reader(io.StringIO(record_text, newline="")))
    if any(len(row) != 3 for row in rows):
        raise RuntimeError("Wheel RECORD chứa dòng không hợp lệ")

    record_names = [row[0] for row in rows]
    if len(record_names) != len(set(record_names)):
        raise RuntimeError("Wheel RECORD chứa entry trùng tên")
    _reject_path_collisions(record_names, artifact="Wheel RECORD")
    for name in record_names:
        _validate_archive_path(name, artifact="Wheel RECORD")

    recorded_members = set(record_names)
    if recorded_members != members:
        missing = sorted(members - recorded_members)
        unexpected = sorted(recorded_members - members)
        details = [
            *(f"thiếu {name}" for name in missing[:3]),
            *(f"thừa {name}" for name in unexpected[:3]),
        ]
        raise RuntimeError("Wheel RECORD không khớp artifact: " + ", ".join(details))

    for name, digest, size in rows:
        if name == record_path:
            if digest or size:
                raise RuntimeError("Wheel RECORD phải để trống hash/size của chính nó")
            continue
        payload = archive.read(name)
        if digest != _record_digest(payload):
            raise RuntimeError(f"Wheel RECORD sai SHA-256 cho {name}")
        if size != str(len(payload)):
            raise RuntimeError(f"Wheel RECORD sai size cho {name}")


def verify_wheel(wheel_path: Path) -> None:
    """Ensure the wheel exposes `igchat_v2` cleanly at top level."""
    if not wheel_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy wheel: {wheel_path}")

    with zipfile.ZipFile(wheel_path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise RuntimeError("Wheel chứa entry trùng tên")
        _reject_path_collisions(names, artifact="Wheel")

        allowed_directories = _allowed_directories(ALLOWED_WHEEL_MEMBERS)
        file_names: list[str] = []
        for info in infos:
            path = _validate_archive_path(info.filename, artifact="Wheel")
            normalized = path.as_posix().rstrip("/")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise RuntimeError(
                    f"Wheel chứa symbolic link không được phép: {info.filename}"
                )
            if info.is_dir():
                file_type = stat.S_IFMT(mode)
                if info.create_system == 3 and file_type not in {0, stat.S_IFDIR}:
                    raise RuntimeError(
                        f"Wheel chứa entry directory không hợp lệ: {info.filename}"
                    )
                if normalized not in allowed_directories:
                    raise RuntimeError(
                        f"Wheel chứa thư mục ngoài allowlist: {info.filename}"
                    )
                continue
            file_type = stat.S_IFMT(mode)
            if info.create_system == 3 and file_type not in {0, stat.S_IFREG}:
                raise RuntimeError(
                    f"Wheel chứa entry không phải file thường: {info.filename}"
                )
            file_names.append(normalized)

        members = set(file_names)
        missing = sorted(ALLOWED_WHEEL_MEMBERS - members)
        if missing:
            raise RuntimeError(f"Wheel thiếu file bắt buộc: {', '.join(missing)}")
        unexpected = sorted(members - ALLOWED_WHEEL_MEMBERS)
        if unexpected:
            raise RuntimeError(
                "Wheel chứa file ngoài allowlist: " + ", ".join(unexpected[:5])
            )

        metadata_path = f"{WHEEL_DIST_INFO_ROOT}/METADATA"
        metadata = Parser().parsestr(
            archive.read(metadata_path).decode("utf-8", errors="strict")
        )
        _verify_wheel_record(archive, members)

    if metadata.get_all("Name", []) != [DISTIBUTION_NAME]:
        raise RuntimeError(
            f"Tên distribution không đúng: {metadata.get_all('Name', [])!r}"
        )
    if metadata.get_all("Version", []) != [EXPECTED_VERSION]:
        raise RuntimeError(
            "Version trong wheel không đúng: "
            f"{metadata.get_all('Version', [])!r} != {[EXPECTED_VERSION]!r}"
        )


def verify_sdist(sdist_path: Path) -> None:
    """Ensure the sdist contains only canonical project sources."""
    if not sdist_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy sdist: {sdist_path}")

    with tarfile.open(sdist_path, mode="r:gz") as archive:
        archive_members = archive.getmembers()
        names = [member.name for member in archive_members]
        if len(names) != len(set(names)):
            raise RuntimeError("Sdist chứa entry trùng tên")
        _reject_path_collisions(names, artifact="Sdist")

        allowed_directories = _allowed_directories(ALLOWED_SDIST_FILES)
        file_names: list[str] = []
        pkg_info_payload: bytes | None = None
        for member in archive_members:
            path = _validate_archive_path(member.name, artifact="Sdist")
            if not path.parts or path.parts[0] != EXPECTED_SDIST_ROOT:
                raise RuntimeError(
                    f"Sdist phải dùng thư mục gốc {EXPECTED_SDIST_ROOT!r}"
                )
            relative = PurePosixPath(*path.parts[1:]).as_posix()
            if member.isdir():
                if relative != "." and relative not in allowed_directories:
                    raise RuntimeError(
                        f"Sdist chứa thư mục ngoài allowlist: {relative}"
                    )
                continue
            if not member.isfile():
                raise RuntimeError(
                    f"Sdist chứa entry không phải file thường: {member.name}"
                )
            file_names.append(relative)
            if relative == "PKG-INFO":
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise RuntimeError("Không đọc được PKG-INFO trong sdist")
                pkg_info_payload = extracted.read()

    members = set(file_names)
    missing = sorted(ALLOWED_SDIST_FILES - members)
    if missing:
        raise RuntimeError(f"Sdist thiếu file bắt buộc: {', '.join(missing)}")
    unexpected = sorted(members - ALLOWED_SDIST_FILES)
    if unexpected:
        raise RuntimeError(
            "Sdist chứa file ngoài allowlist: " + ", ".join(unexpected[:5])
        )
    if pkg_info_payload is None:
        raise RuntimeError("Sdist thiếu PKG-INFO")
    pkg_info = Parser().parsestr(pkg_info_payload.decode("utf-8", errors="strict"))
    if pkg_info.get_all("Name", []) != [DISTIBUTION_NAME]:
        raise RuntimeError(
            f"Tên distribution trong sdist sai: {pkg_info.get_all('Name', [])!r}"
        )
    if pkg_info.get_all("Version", []) != [EXPECTED_VERSION]:
        raise RuntimeError(
            "Version trong sdist không đúng: "
            f"{pkg_info.get_all('Version', [])!r} != {[EXPECTED_VERSION]!r}"
        )


def verify_imports() -> None:
    """Import only the public v3.0.0 namespace of `igchat_v2`."""
    imported = [importlib.import_module(package) for package in PACKAGE_NAMES]
    if any(module is None for module in imported):
        raise RuntimeError("Không import được đầy đủ package công khai")

    try:
        installed_version = version(DISTIBUTION_NAME)
    except PackageNotFoundError as exc:
        raise RuntimeError(f"Chưa cài distribution {DISTIBUTION_NAME}") from exc
    if installed_version != EXPECTED_VERSION:
        raise RuntimeError(
            f"Version đã cài không đúng: {installed_version!r} != {EXPECTED_VERSION!r}"
        )

    public_package = importlib.import_module("igchat_v2")
    for export in (
        "InstagramSession",
        "bootstrap_session",
        "login_with_credentials",
        "BridgeProcess",
        "BridgeActions",
        "ReconnectPolicy",
        "DirectListener",
        "send_text_message",
        "create_note",
        "get_user_profile",
        "publish_photo",
        "InstagramBot",
    ):
        if not hasattr(public_package, export):
            raise RuntimeError(f"igchat_v2 thiếu public export {export}")

    for subpkg in (
        "igchat_v2.core",
        "igchat_v2.auth",
        "igchat_v2.bridge",
        "igchat_v2.direct",
        "igchat_v2.social",
        "igchat_v2.bot",
    ):
        importlib.import_module(subpkg)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "artifact",
        nargs="?",
        type=Path,
        help="Wheel/sdist cần kiểm tra; bỏ trống để chỉ smoke-test import.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.artifact is not None:
        if args.artifact.name.endswith(".whl"):
            verify_wheel(args.artifact)
        elif args.artifact.name.endswith(".tar.gz"):
            verify_sdist(args.artifact)
        else:
            raise RuntimeError(f"Artifact không được hỗ trợ: {args.artifact}")
    verify_imports()
    print("Distribution smoke test (igchat-v2 v3.0.0): OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
