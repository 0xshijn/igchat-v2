"""Instagram Direct Chat Themes, Group Polls, and Silent Dispatching."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from ..core.http import DEFAULT_TIMEOUT_SECONDS, post_graphql_async
from ..core.models import InstagramSession, normalize_session

DOC_ID_SET_THEME = "28384918239019283"
DOC_ID_CREATE_POLL = "39281928391029384"
DOC_ID_VOTE_POLL = "39281928391029385"


class ChatTheme:
    """Standard Instagram Direct theme identifiers and presets."""

    DEFAULT = "0"
    CYBERPUNK = "1001"
    OCEAN = "1002"
    AUTUMN = "1003"
    LOFI = "1004"
    NEON = "1005"
    SUNSET = "1006"
    MONOKAI = "1007"
    COTTON_CANDY = "1008"
    LAVENDER = "1009"

    ALL_THEMES: dict[str, str] = {
        "default": DEFAULT,
        "cyberpunk": CYBERPUNK,
        "ocean": OCEAN,
        "autumn": AUTUMN,
        "lofi": LOFI,
        "neon": NEON,
        "sunset": SUNSET,
        "monokai": MONOKAI,
        "cotton_candy": COTTON_CANDY,
        "lavender": LAVENDER,
    }

    @classmethod
    def resolve_theme_id(cls, name_or_id: str) -> str:
        cleaned = name_or_id.strip().lower()
        if cleaned in cls.ALL_THEMES:
            return cls.ALL_THEMES[cleaned]
        return name_or_id.strip()


async def set_thread_theme(
    session: InstagramSession | Mapping[str, Any],
    thread_id: int | str,
    theme_name_or_id: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Change the visual theme of an Instagram Direct thread."""
    sess = normalize_session(session)
    clean_thread = str(thread_id).strip()
    theme_id = ChatTheme.resolve_theme_id(theme_name_or_id)
    if not clean_thread:
        raise ValueError("thread_id không được để trống.")

    variables = {
        "input": {
            "thread_id": clean_thread,
            "theme_id": theme_id,
        }
    }
    return await post_graphql_async(
        sess,
        doc_id=DOC_ID_SET_THEME,
        variables=variables,
        friendly_name="IGDSetThreadThemeMutation",
        client=client,
        timeout=timeout,
    )


async def create_direct_poll(
    session: InstagramSession | Mapping[str, Any],
    thread_id: int | str,
    question: str,
    options: Sequence[str],
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Create an interactive Poll in an Instagram Direct group thread."""
    sess = normalize_session(session)
    clean_thread = str(thread_id).strip()
    clean_question = question.strip()
    clean_options = [opt.strip() for opt in options if opt.strip()]

    if not clean_thread:
        raise ValueError("thread_id không được để trống.")
    if not clean_question:
        raise ValueError("Câu hỏi Poll không được để trống.")
    if len(clean_options) < 2:
        raise ValueError("Poll phải có ít nhất 2 phương án lựa chọn.")

    variables = {
        "input": {
            "thread_id": clean_thread,
            "question": clean_question,
            "options": clean_options,
        }
    }
    return await post_graphql_async(
        sess,
        doc_id=DOC_ID_CREATE_POLL,
        variables=variables,
        friendly_name="IGDCreateDirectPollMutation",
        client=client,
        timeout=timeout,
    )


async def vote_direct_poll(
    session: InstagramSession | Mapping[str, Any],
    thread_id: int | str,
    poll_id: str,
    option_id: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Cast a vote on an active Instagram Direct group poll."""
    sess = normalize_session(session)
    clean_thread = str(thread_id).strip()
    if not clean_thread or not poll_id.strip() or not option_id.strip():
        raise ValueError("thread_id, poll_id và option_id không được để trống.")

    variables = {
        "input": {
            "thread_id": clean_thread,
            "poll_id": poll_id.strip(),
            "option_id": option_id.strip(),
        }
    }
    return await post_graphql_async(
        sess,
        doc_id=DOC_ID_VOTE_POLL,
        variables=variables,
        friendly_name="IGDVoteDirectPollMutation",
        client=client,
        timeout=timeout,
    )


def format_silent_message(text: str) -> str:
    """Prepend the Instagram @silent tag to dispatch without push notification sound."""
    cleaned = text.strip()
    if cleaned.startswith("@silent"):
        return cleaned
    return f"@silent {cleaned}"


__all__ = [
    "ChatTheme",
    "create_direct_poll",
    "format_silent_message",
    "set_thread_theme",
    "vote_direct_poll",
]
