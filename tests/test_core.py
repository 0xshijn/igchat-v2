"""Unit tests for igchat_v2.core modules."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from igchat_v2.core.console import configure_utf8_console, safe_print
from igchat_v2.core.errors import (
    SecurityViolationError,
    SessionCookieError,
)
from igchat_v2.core.http import (
    validate_public_http_url,
    validate_timeout,
)
from igchat_v2.core.models import (
    InstagramSession,
    format_cookie_header,
    normalize_session,
    parse_cookie_header,
)
from igchat_v2.core.permissions import (
    create_private_json_file,
    require_private_file,
    set_private_file_permissions,
)
from igchat_v2.core.redact import (
    redact_sensitive_data,
    redact_sensitive_text,
    sanitize_log_message,
)
from igchat_v2.core.utils import (
    build_graphql_form,
    build_ig_headers,
    compute_jazoest,
    generate_offline_threading_id,
    parse_json_response,
    strip_json_prefix,
)


def test_models_and_session_validation(mock_session: InstagramSession) -> None:
    assert mock_session.ig_user_id == "17841400000000001"
    assert mock_session.ds_user_id == "17841400000000001"
    cookie_dict = mock_session.as_cookie_dict()
    assert cookie_dict["sessionid"].startswith("17841400000000001")
    assert cookie_dict["csrftoken"] == "mock_csrf_token_value"

    as_dict = mock_session.to_dict()
    reconstructed = InstagramSession.from_mapping(as_dict)
    assert reconstructed.ig_user_id == mock_session.ig_user_id
    assert reconstructed.sessionid == mock_session.sessionid

    norm = normalize_session(as_dict)
    assert isinstance(norm, InstagramSession)
    assert norm.ig_user_id == mock_session.ig_user_id

    with pytest.raises(SessionCookieError):
        InstagramSession(
            ig_user_id="invalid_not_digits",
            sessionid="valid_token",
            csrftoken="valid_csrf",
            cookies="ds_user_id=abc",
        )

    with pytest.raises(SessionCookieError):
        InstagramSession(
            ig_user_id="12345678",
            sessionid="",
            csrftoken="valid_csrf",
            cookies="ds_user_id=12345678",
        )


def test_cookie_helpers() -> None:
    raw = "sessionid=xyz123; csrftoken=csrf456; ds_user_id=789;"
    parsed = parse_cookie_header(raw)
    assert parsed == {
        "sessionid": "xyz123",
        "csrftoken": "csrf456",
        "ds_user_id": "789",
    }
    formatted = format_cookie_header(parsed)
    assert "sessionid=xyz123" in formatted
    assert "ds_user_id=789" in formatted


def test_redact_sensitive_text_and_data() -> None:
    raw_text = "Login failed with sessionid=secret_token_12345 and user 17841412345678901 on https://www.instagram.com/direct/t/123/?query=val"
    redacted = redact_sensitive_text(raw_text)
    assert "secret_token_12345" not in redacted
    assert "[redacted]" in redacted
    assert "[redacted-id]" in redacted
    assert "/[redacted-path]" in redacted

    data = {
        "cookies": "secret_cookie",
        "nested": {"sessionid": "token_abc", "public_info": "hello"},
        "list": ["password=pass123", {"token": "secret"}],
    }
    cleaned = redact_sensitive_data(data)
    assert cleaned["cookies"] == "[redacted]"
    assert cleaned["nested"]["sessionid"] == "[redacted]"
    assert cleaned["nested"]["public_info"] == "hello"

    msg = sanitize_log_message("Event received", {"sessionid": "123"})
    assert "123" not in msg


def test_permissions_atomic_json(tmp_path: Path) -> None:
    file_path = tmp_path / "secret.json"
    create_private_json_file(file_path, '{"test": 1}\n')
    assert file_path.is_file()
    assert require_private_file(file_path) == file_path

    set_private_file_permissions(file_path)

    symlink_path = tmp_path / "symlink.json"
    try:
        os.symlink(file_path, symlink_path)
        with pytest.raises(PermissionError):
            require_private_file(symlink_path)
    except (OSError, NotImplementedError):
        pass


def test_utils_helpers(mock_session: InstagramSession) -> None:
    assert compute_jazoest("token") == f"2{sum(ord(c) for c in 'token')}"
    otid = generate_offline_threading_id()
    assert otid.isdigit()
    assert len(otid) > 10

    raw_json = 'for (;;); {"status": "ok", "count": 5}'
    assert strip_json_prefix(raw_json) == '{"status": "ok", "count": 5}'
    parsed = parse_json_response(raw_json)
    assert parsed["status"] == "ok"

    headers = build_ig_headers(mock_session)
    assert headers["X-IG-App-ID"] == "936619743392459"
    assert "mock_session_token" in headers["Cookie"]

    form = build_graphql_form(mock_session, doc_id="12345", variables={"foo": "bar"})
    assert form["doc_id"] == "12345"
    assert '"foo":"bar"' in form["variables"]


def test_ssrf_guards() -> None:
    assert validate_public_http_url("https://www.instagram.com/test", resolve_dns=False)

    with pytest.raises(SecurityViolationError):
        validate_public_http_url("http://127.0.0.1/admin", resolve_dns=False)

    with pytest.raises(SecurityViolationError):
        validate_public_http_url("http://localhost:8080", resolve_dns=False)

    with pytest.raises(SecurityViolationError):
        validate_public_http_url("http://10.0.0.1/metadata", resolve_dns=False)

    with pytest.raises(SecurityViolationError):
        validate_public_http_url("http://192.168.1.1/router", resolve_dns=False)

    with pytest.raises(SecurityViolationError):
        validate_public_http_url("http://100.64.0.1/cgnat", resolve_dns=False)

    with pytest.raises(SecurityViolationError):
        validate_public_http_url("ftp://example.com/file", resolve_dns=False)

    with pytest.raises(SecurityViolationError):
        validate_public_http_url("http://user:pass@example.com", resolve_dns=False)

    assert validate_timeout(10.0) == 10.0
    with pytest.raises(ValueError):
        validate_timeout(-1.0)
    with pytest.raises(ValueError):
        validate_timeout(0.0)


def test_console_helpers() -> None:
    configure_utf8_console()
    safe_print("Test Unicode message: Tiếng Việt có dấu 🚀")
