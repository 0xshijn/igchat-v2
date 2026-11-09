from __future__ import annotations

import pytest

from igchat.auth.vault import export_vault_session, load_vault_session
from igchat.core.errors import AuthenticationError
from igchat.core.models import InstagramSession


def test_vault_roundtrip():
    session = InstagramSession(
        ig_user_id="123456789",
        sessionid="test_session_id",
        csrftoken="test_csrf_token",
        cookies="sessionid=test_session_id; ds_user_id=123456789; csrftoken=test_csrf_token;",
    )
    passphrase = "my_super_secret_passphrase_123"

    vault_json = export_vault_session(session, passphrase)
    assert "ciphertext" in vault_json
    assert "test_session_id" not in vault_json  # Ensure zero cleartext leakage

    restored = load_vault_session(vault_json, passphrase)
    assert restored.ig_user_id == "123456789"
    assert restored.sessionid == "test_session_id"
    assert restored.csrftoken == "test_csrf_token"


def test_vault_wrong_passphrase():
    session = InstagramSession(
        ig_user_id="123456789",
        sessionid="test_session_id",
        csrftoken="test_csrf_token",
        cookies="sessionid=test_session_id; ds_user_id=123456789;",
    )
    vault_json = export_vault_session(session, "correct_passphrase_123")

    with pytest.raises(AuthenticationError):
        load_vault_session(vault_json, "wrong_passphrase_456")

