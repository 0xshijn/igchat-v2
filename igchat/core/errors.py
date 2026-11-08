"""Domain-specific exception hierarchy for igchat-v2."""

from __future__ import annotations


class IGChatError(Exception):
    """Base exception for all igchat-v2 errors."""


class SecurityViolationError(IGChatError, ValueError):
    """Raised when an SSRF, path, or unsafe parameter boundary is violated."""


class SessionError(IGChatError):
    """Raised when an Instagram session cannot be bootstrapped or refreshed."""


class SessionCookieError(SessionError, ValueError):
    """Raised when required Instagram session cookies are missing or malformed."""


class AuthenticationError(IGChatError):
    """Raised when Instagram rejects credentials or invalidates an active session."""


class CheckpointRequiredError(AuthenticationError):
    """Raised when Instagram demands a checkpoint or challenge verification."""

    def __init__(self, message: str, *, checkpoint_path: str = "") -> None:
        super().__init__(message)
        self.checkpoint_path = checkpoint_path


class BridgeError(IGChatError):
    """Raised when the native Go Instagram Direct bridge fails or rejects an RPC."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "",
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable


class BridgeProtocolError(BridgeError):
    """Raised when the Go bridge violates the line JSON-RPC v1 contract."""
