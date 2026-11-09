"""Zero-Leak Encrypted Session Vault for Instagram Sessions.

Protects credentials and session cookies using PBKDF2-HMAC-SHA256 key derivation
and authenticated encryption, preventing cleartext cookie exposure in git or disk.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from typing import Any

from ..core.errors import AuthenticationError
from ..core.models import InstagramSession

VAULT_VERSION = 1
PBKDF2_ITERATIONS = 200_000


def _derive_keys(passphrase: str, salt: bytes) -> tuple[bytes, bytes]:
    """Derive 32-byte encryption key and 32-byte auth key via PBKDF2."""
    material = hashlib.pbkdf2_hmac(
        "sha256",
        passphrase.encode("utf-8"),
        salt,
        iterations=PBKDF2_ITERATIONS,
        dklen=64,
    )
    return material[:32], material[32:]


def _xor_cipher(data: bytes, key: bytes, nonce: bytes) -> bytes:
    """Stream cipher using SHA-256 counter blocks."""
    out = bytearray(len(data))
    block_index = 0
    key_stream = b""
    stream_pos = 0

    for i in range(len(data)):
        if stream_pos >= len(key_stream):
            counter_bytes = block_index.to_bytes(4, byteorder="big")
            key_stream = hashlib.sha256(key + nonce + counter_bytes).digest()
            block_index += 1
            stream_pos = 0
        out[i] = data[i] ^ key_stream[stream_pos]
        stream_pos += 1

    return bytes(out)


def export_vault_session(session: InstagramSession, passphrase: str) -> str:
    """Serialize and encrypt an InstagramSession into an armored JSON vault string."""
    clean_pass = passphrase.strip()
    if len(clean_pass) < 6:
        raise ValueError("Passphrase phải có ít nhất 6 ký tự.")

    payload = {
        "ig_user_id": session.ig_user_id,
        "sessionid": session.sessionid,
        "csrftoken": session.csrftoken,
        "cookies": session.cookies,
        "ds_user_id": session.ds_user_id,
        "eimu_id": session.eimu_id,
        "mid": session.mid,
        "ig_did": session.ig_did,
        "rur": session.rur,
        "fb_dtsg": session.fb_dtsg,
    }
    plaintext = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    enc_key, auth_key = _derive_keys(clean_pass, salt)

    ciphertext = _xor_cipher(plaintext, enc_key, nonce)
    tag = hmac.new(auth_key, nonce + ciphertext, hashlib.sha256).digest()

    vault_dict = {
        "version": VAULT_VERSION,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "tag": base64.b64encode(tag).decode("ascii"),
    }
    return json.dumps(vault_dict, indent=2)


def load_vault_session(
    vault_content: str | dict[str, Any],
    passphrase: str,
) -> InstagramSession:
    """Decrypt and deserialize an armored JSON vault string back into an InstagramSession."""
    clean_pass = passphrase.strip()
    if isinstance(vault_content, str):
        try:
            data = json.loads(vault_content)
        except json.JSONDecodeError as exc:
            raise AuthenticationError(
                f"Dữ liệu vault không đúng định dạng JSON: {exc}"
            ) from exc
    elif isinstance(vault_content, dict):
        data = vault_content
    else:
        raise TypeError("vault_content phải là chuỗi JSON hoặc dictionary.")

    try:
        salt = base64.b64decode(data["salt"])
        nonce = base64.b64decode(data["nonce"])
        ciphertext = base64.b64decode(data["ciphertext"])
        expected_tag = base64.b64decode(data["tag"])
    except (KeyError, ValueError) as exc:
        raise AuthenticationError(
            "File vault thiếu các trường bảo mật bắt buộc."
        ) from exc

    enc_key, auth_key = _derive_keys(clean_pass, salt)
    computed_tag = hmac.new(auth_key, nonce + ciphertext, hashlib.sha256).digest()

    if not hmac.compare_digest(computed_tag, expected_tag):
        raise AuthenticationError(
            "Giải mã vault thất bại: Passphrase không đúng hoặc file đã bị sửa đổi."
        )

    plaintext = _xor_cipher(ciphertext, enc_key, nonce)
    try:
        payload = json.loads(plaintext.decode("utf-8"))
    except Exception as exc:
        raise AuthenticationError(f"Nội dung giải mã không hợp lệ: {exc}") from exc

    return InstagramSession(
        ig_user_id=payload.get("ig_user_id", ""),
        sessionid=payload.get("sessionid", ""),
        csrftoken=payload.get("csrftoken", ""),
        cookies=payload.get("cookies", ""),
        ds_user_id=payload.get("ds_user_id", ""),
        eimu_id=payload.get("eimu_id", ""),
        mid=payload.get("mid", ""),
        ig_did=payload.get("ig_did", ""),
        rur=payload.get("rur", ""),
        fb_dtsg=payload.get("fb_dtsg", ""),
    )


__all__ = [
    "export_vault_session",
    "load_vault_session",
]
