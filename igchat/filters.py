"""Composable declarative event filters for Instagram Direct messages and events.

Inspired by Telethon & Pyrogram, customized for Instagram Direct event semantics.
Supports bitwise operators: & (AND), | (OR), ~ (NOT), ^ (XOR).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any, Pattern


class Filter:
    """Base class for all composable Instagram Direct event filters."""

    def __call__(self, event: dict[str, Any]) -> bool:
        raise NotImplementedError

    def __and__(self, other: Filter | Callable[[dict[str, Any]], bool]) -> Filter:
        return _AndFilter(self, _wrap(other))

    def __or__(self, other: Filter | Callable[[dict[str, Any]], bool]) -> Filter:
        return _OrFilter(self, _wrap(other))

    def __invert__(self) -> Filter:
        return _InvertFilter(self)

    def __xor__(self, other: Filter | Callable[[dict[str, Any]], bool]) -> Filter:
        return _XorFilter(self, _wrap(other))


def _wrap(f: Filter | Callable[[dict[str, Any]], bool]) -> Filter:
    if isinstance(f, Filter):
        return f
    if callable(f):
        return _LambdaFilter(f)
    raise TypeError(f"Đối tượng {f!r} không phải là Filter hoặc callable.")


class _LambdaFilter(Filter):
    def __init__(self, func: Callable[[dict[str, Any]], bool]) -> None:
        self.func = func

    def __call__(self, event: dict[str, Any]) -> bool:
        return bool(self.func(event))

    def __repr__(self) -> str:
        return f"Filter({getattr(self.func, '__name__', 'lambda')})"


class _AndFilter(Filter):
    def __init__(self, left: Filter, right: Filter) -> None:
        self.left = left
        self.right = right

    def __call__(self, event: dict[str, Any]) -> bool:
        return self.left(event) and self.right(event)

    def __repr__(self) -> str:
        return f"({self.left!r} & {self.right!r})"


class _OrFilter(Filter):
    def __init__(self, left: Filter, right: Filter) -> None:
        self.left = left
        self.right = right

    def __call__(self, event: dict[str, Any]) -> bool:
        return self.left(event) or self.right(event)

    def __repr__(self) -> str:
        return f"({self.left!r} | {self.right!r})"


class _InvertFilter(Filter):
    def __init__(self, target: Filter) -> None:
        self.target = target

    def __call__(self, event: dict[str, Any]) -> bool:
        return not self.target(event)

    def __repr__(self) -> str:
        return f"(~{self.target!r})"


class _XorFilter(Filter):
    def __init__(self, left: Filter, right: Filter) -> None:
        self.left = left
        self.right = right

    def __call__(self, event: dict[str, Any]) -> bool:
        return bool(self.left(event)) ^ bool(self.right(event))

    def __repr__(self) -> str:
        return f"({self.left!r} ^ {self.right!r})"


def _get_event_data(event: dict[str, Any]) -> dict[str, Any]:
    data = event.get("data")
    if isinstance(data, dict):
        return data
    return event


class _AllFilter(Filter):
    def __call__(self, event: dict[str, Any]) -> bool:
        return True

    def __repr__(self) -> str:
        return "filters.all"


class _TextFilter(Filter):
    def __call__(self, event: dict[str, Any]) -> bool:
        data = _get_event_data(event)
        text = str(data.get("text") or "").strip()
        return bool(text)

    def __repr__(self) -> str:
        return "filters.text"


class _CommandFilter(Filter):
    def __init__(
        self,
        commands: str | Sequence[str],
        prefixes: str | Sequence[str] = ("/", "!"),
        case_sensitive: bool = False,
    ) -> None:
        if isinstance(commands, str):
            commands = [commands]
        self.prefixes = tuple(prefixes)
        self.case_sensitive = case_sensitive
        self.commands = tuple(
            cmd if case_sensitive else cmd.lower() for cmd in commands
        )

    def __call__(self, event: dict[str, Any]) -> bool:
        data = _get_event_data(event)
        text = str(data.get("text") or "").strip()
        if not text:
            return False
        for prefix in self.prefixes:
            if text.startswith(prefix):
                without_prefix = text[len(prefix) :].strip()
                cmd_token = (
                    without_prefix.split(maxsplit=1)[0] if without_prefix else ""
                )
                check = cmd_token if self.case_sensitive else cmd_token.lower()
                if check in self.commands:
                    return True
        return False

    def __repr__(self) -> str:
        return f"filters.command({self.commands!r}, prefixes={self.prefixes!r})"


class _RegexFilter(Filter):
    def __init__(self, pattern: str | Pattern[str]) -> None:
        self.pattern = re.compile(pattern) if isinstance(pattern, str) else pattern

    def __call__(self, event: dict[str, Any]) -> bool:
        data = _get_event_data(event)
        text = str(data.get("text") or "")
        return bool(self.pattern.search(text))

    def __repr__(self) -> str:
        return f"filters.regex({self.pattern.pattern!r})"


class _MediaFilter(Filter):
    def __init__(self, kind: str | None = None) -> None:
        self.kind = kind  # None, "photo", "video", "voice"

    def __call__(self, event: dict[str, Any]) -> bool:
        data = _get_event_data(event)
        attachments = data.get("attachments") or []
        item_type = str(data.get("item_type") or data.get("itemType") or "").lower()
        if self.kind == "voice":
            return (
                "voice" in item_type
                or "audio" in item_type
                or any(att.get("type") in {"voice", "audio"} for att in attachments)
            )
        if self.kind == "photo":
            return (
                "image" in item_type
                or "photo" in item_type
                or any(att.get("type") in {"image", "photo"} for att in attachments)
            )
        if self.kind == "video":
            return "video" in item_type or any(
                att.get("type") in {"video", "clip"} for att in attachments
            )
        return bool(attachments) or bool(item_type and item_type != "text")

    def __repr__(self) -> str:
        return f"filters.{self.kind or 'media'}"


class _StoryReplyFilter(Filter):
    def __call__(self, event: dict[str, Any]) -> bool:
        data = _get_event_data(event)
        item_type = str(data.get("item_type") or data.get("itemType") or "").lower()
        story_share = data.get("story_share") or data.get("storyShare")
        return "story" in item_type or bool(story_share)

    def __repr__(self) -> str:
        return "filters.story_reply"


class _ReactionFilter(Filter):
    def __call__(self, event: dict[str, Any]) -> bool:
        ev_type = str(event.get("type") or "")
        data = _get_event_data(event)
        return ev_type == "reaction" or "reaction" in data or "emoji" in data

    def __repr__(self) -> str:
        return "filters.reaction"


class _GroupFilter(Filter):
    def __init__(self, is_group: bool = True) -> None:
        self.is_group = is_group

    def __call__(self, event: dict[str, Any]) -> bool:
        data = _get_event_data(event)
        thread_type = data.get("thread_type") or data.get("threadType")
        flag = data.get("is_group") or data.get("isGroup")
        actual_group = bool(flag) or thread_type == 2
        return actual_group == self.is_group

    def __repr__(self) -> str:
        return "filters.group" if self.is_group else "filters.private"


class _SenderFilter(Filter):
    def __init__(self, *senders: int | str) -> None:
        self.senders = {str(s).strip() for s in senders}

    def __call__(self, event: dict[str, Any]) -> bool:
        data = _get_event_data(event)
        sid = str(data.get("senderId") or data.get("sender_id") or "").strip()
        return sid in self.senders

    def __repr__(self) -> str:
        return f"filters.sender({sorted(self.senders)!r})"


class _ThreadFilter(Filter):
    def __init__(self, *threads: int | str) -> None:
        self.threads = {str(t).strip() for t in threads}

    def __call__(self, event: dict[str, Any]) -> bool:
        data = _get_event_data(event)
        tid = str(data.get("threadId") or data.get("thread_id") or "").strip()
        return tid in self.threads

    def __repr__(self) -> str:
        return f"filters.thread({sorted(self.threads)!r})"


class _SilentFilter(Filter):
    def __call__(self, event: dict[str, Any]) -> bool:
        data = _get_event_data(event)
        text = str(data.get("text") or "").strip()
        is_silent = data.get("is_silent") or data.get("isSilent")
        return bool(is_silent) or text.startswith("@silent ")

    def __repr__(self) -> str:
        return "filters.silent"


# Pre-instantiated singleton filters
all = _AllFilter()
text = _TextFilter()
media = _MediaFilter()
photo = _MediaFilter("photo")
video = _MediaFilter("video")
voice = _MediaFilter("voice")
story_reply = _StoryReplyFilter()
reaction = _ReactionFilter()
group = _GroupFilter(True)
private = _GroupFilter(False)
dm = private
silent = _SilentFilter()

# Factory functions
command = _CommandFilter
regex = _RegexFilter
sender = _SenderFilter
thread = _ThreadFilter

__all__ = [
    "Filter",
    "all",
    "command",
    "dm",
    "group",
    "media",
    "photo",
    "private",
    "reaction",
    "regex",
    "sender",
    "silent",
    "story_reply",
    "text",
    "thread",
    "video",
    "voice",
]
