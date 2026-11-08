"""Authentication, session bootstrap, and credential/cookie storage."""

from __future__ import annotations

from .login import LoginResult, login_with_credentials
from .session import bootstrap_session
from .storage import EnvSessionStorage, FileSessionStorage, SessionStorage

__all__ = [
    "EnvSessionStorage",
    "FileSessionStorage",
    "LoginResult",
    "SessionStorage",
    "bootstrap_session",
    "login_with_credentials",
]
