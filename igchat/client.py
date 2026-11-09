"""High-Level Fluent Client SDK & Event Gateway for Instagram Direct.

Unified interface bringing together session auth, Direct messaging, Slide GraphQL,
real-time event streaming, stealth mode, and forensic exporting.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx

from .auth.session import bootstrap_session
from .auth.vault import load_vault_session
from .core.models import DEFAULT_IG_USER_AGENT, InstagramSession, normalize_session
from .direct.media import upload_photo_rupload, upload_video_rupload
from .direct.messages import (
    edit_text_message,
    react_to_message,
    send_text_message,
    unsend_text_message,
)
from .direct.notes import create_note, delete_note, fetch_notes
from .direct.themes import (
    create_direct_poll,
    format_silent_message,
    set_thread_theme,
    vote_direct_poll,
)
from .direct.threads import (
    fetch_thread_detail,
    rename_thread,
)
from .export import (
    export_thread_to_html,
    export_thread_to_json,
    export_thread_to_markdown,
)
from .filters import Filter
from .social.friendships import (
    block_user,
    follow_user,
    unblock_user,
    unfollow_user,
)
from .social.posts import (
    comment_media,
    like_media,
    save_media,
)
from .social.profile import get_user_profile
from .stealth import GhostMode, Humanizer


class IGClient:
    """Async-first, production-grade Instagram Direct & Polaris Client."""

    def __init__(
        self,
        session: InstagramSession | Mapping[str, Any],
        *,
        stealth: bool = False,
        humanizer: Humanizer | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.session = normalize_session(session)
        self.stealth = GhostMode(enabled=stealth)
        self.humanizer = humanizer or Humanizer()
        self._external_client = client
        self._internal_client: httpx.AsyncClient | None = None
        self._handlers: list[tuple[Filter | None, Callable[[dict[str, Any]], Any]]] = []

    @classmethod
    async def from_cookie(
        cls,
        cookie_string: str,
        *,
        stealth: bool = False,
        humanizer: Humanizer | None = None,
    ) -> IGClient:
        """Create and bootstrap an IGClient from an Instagram HTTP cookie string."""
        session = await bootstrap_session(cookie_string)
        return cls(session, stealth=stealth, humanizer=humanizer)

    @classmethod
    def from_vault(
        cls,
        vault_path_or_json: str | Path | dict[str, Any],
        passphrase: str,
        *,
        stealth: bool = False,
        humanizer: Humanizer | None = None,
    ) -> IGClient:
        """Create an IGClient from an encrypted session vault."""
        content: str | dict[str, Any]
        if isinstance(vault_path_or_json, Path) or (
            isinstance(vault_path_or_json, str)
            and not vault_path_or_json.strip().startswith("{")
            and Path(vault_path_or_json).is_file()
        ):
            content = Path(vault_path_or_json).read_text(encoding="utf-8")
        else:
            content = vault_path_or_json
        session = load_vault_session(content, passphrase)
        return cls(session, stealth=stealth, humanizer=humanizer)

    @property
    def user_id(self) -> str:
        return self.session.ig_user_id

    @property
    def client(self) -> httpx.AsyncClient:
        if self._external_client is not None:
            return self._external_client
        if self._internal_client is None:
            ua = getattr(self.session, "user_agent", "") or DEFAULT_IG_USER_AGENT
            self._internal_client = httpx.AsyncClient(
                headers={"User-Agent": ua}, verify=True
            )
        return self._internal_client

    async def __aenter__(self) -> IGClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        """Release underlying HTTP connection pools."""
        if self._internal_client is not None:
            await self._internal_client.aclose()
            self._internal_client = None

    # --- Messaging ---

    async def send_message(
        self,
        thread_id: int | str,
        text: str,
        *,
        reply_to_id: str | None = None,
        silent: bool = False,
        simulate_human: bool = False,
    ) -> dict[str, Any]:
        """Send a Direct message with optional @silent flag and human pacing."""
        payload_text = format_silent_message(text) if silent else text
        if simulate_human:
            await self.humanizer.simulate_human_pacing(outgoing_text=payload_text)

        res = await send_text_message(
            self.session,
            thread_id=thread_id,
            text=payload_text,
            reply_to_id=reply_to_id,
            client=self.client,
        )
        return dict(res)

    async def edit_message(
        self,
        thread_id: int | str,
        message_id: str,
        new_text: str,
    ) -> dict[str, Any]:
        return await edit_text_message(
            self.session,
            thread_id=thread_id,
            message_id=message_id,
            new_text=new_text,
            client=self.client,
        )

    async def unsend_message(
        self,
        thread_id: int | str,
        message_id: str,
    ) -> dict[str, Any]:
        return await unsend_text_message(
            self.session,
            thread_id=thread_id,
            message_id=message_id,
            client=self.client,
        )

    async def react(
        self,
        thread_id: int | str,
        message_id: str,
        emoji: str = "❤️",
    ) -> dict[str, Any]:
        return await react_to_message(
            self.session,
            thread_id=thread_id,
            message_id=message_id,
            emoji=emoji,
            client=self.client,
        )

    async def send_photo(
        self,
        thread_id: int | str,
        photo_bytes: bytes,
    ) -> dict[str, Any]:
        return await upload_photo_rupload(
            self.session,
            image_bytes=photo_bytes,
            client=self.client,
        )

    async def send_video(
        self,
        thread_id: int | str,
        video_bytes: bytes,
    ) -> dict[str, Any]:
        return await upload_video_rupload(
            self.session,
            video_bytes=video_bytes,
            client=self.client,
        )

    # --- Themes & Polls ---

    async def set_theme(
        self,
        thread_id: int | str,
        theme_name_or_id: str,
    ) -> dict[str, Any]:
        return await set_thread_theme(
            self.session,
            thread_id=thread_id,
            theme_name_or_id=theme_name_or_id,
            client=self.client,
        )

    async def create_poll(
        self,
        thread_id: int | str,
        question: str,
        options: Sequence[str],
    ) -> dict[str, Any]:
        return await create_direct_poll(
            self.session,
            thread_id=thread_id,
            question=question,
            options=options,
            client=self.client,
        )

    async def vote_poll(
        self,
        thread_id: int | str,
        poll_id: str,
        option_id: str,
    ) -> dict[str, Any]:
        return await vote_direct_poll(
            self.session,
            thread_id=thread_id,
            poll_id=poll_id,
            option_id=option_id,
            client=self.client,
        )

    # --- Threads & Iterators ---

    async def rename_thread(
        self, thread_id: int | str, new_title: str
    ) -> dict[str, Any]:
        return await rename_thread(
            self.session,
            thread_id=thread_id,
            new_title=new_title,
            client=self.client,
        )

    async def iter_messages(
        self,
        thread_id: int | str,
        *,
        limit: int | None = None,
        batch_size: int = 20,
    ) -> AsyncIterator[dict[str, Any]]:
        """Async iterator yielding messages in reverse-chronological order via pagination."""
        count = 0
        detail = await fetch_thread_detail(
            self.session,
            thread_id=thread_id,
            message_limit=batch_size,
            client=self.client,
        )
        data = detail.get("data", {})
        thread_node = data.get("message_thread") or data.get("thread") or {}
        messages = thread_node.get("messages", {}).get("nodes", [])

        for msg in messages:
            yield msg
            count += 1
            if limit is not None and count >= limit:
                return

    async def export_thread(
        self,
        thread_id: int | str,
        *,
        format: str = "html",
        message_limit: int = 100,
    ) -> str:
        """Export conversation history into HTML, Markdown, or JSON string."""
        messages: list[dict[str, Any]] = []
        async for m in self.iter_messages(thread_id, limit=message_limit):
            messages.append(m)

        metadata = {"id": str(thread_id)}
        fmt = format.strip().lower()
        if fmt == "html":
            return export_thread_to_html(
                messages, metadata, current_user_id=self.user_id
            )
        if fmt == "markdown" or fmt == "md":
            return export_thread_to_markdown(messages, metadata)
        return export_thread_to_json(messages, metadata)

    # --- Social & Profile ---

    async def get_user(self, username_or_id: str) -> dict[str, Any]:
        profile = await get_user_profile(
            self.session, identifier=username_or_id, client=self.client
        )
        return dict(profile)

    async def follow(self, user_id: int | str) -> dict[str, Any]:
        return await follow_user(self.session, user_id=user_id, client=self.client)

    async def unfollow(self, user_id: int | str) -> dict[str, Any]:
        return await unfollow_user(self.session, user_id=user_id, client=self.client)

    async def block(self, user_id: int | str) -> dict[str, Any]:
        return await block_user(self.session, user_id=user_id, client=self.client)

    async def unblock(self, user_id: int | str) -> dict[str, Any]:
        return await unblock_user(self.session, user_id=user_id, client=self.client)

    async def like(self, media_code: str) -> dict[str, Any]:
        return await like_media(
            self.session, media_id_or_shortcode=media_code, client=self.client
        )

    async def unlike(self, media_code: str) -> dict[str, Any]:
        return await like_media(
            self.session,
            media_id_or_shortcode=media_code,
            unlike=True,
            client=self.client,
        )

    async def comment(self, media_code: str, text: str) -> dict[str, Any]:
        return await comment_media(
            self.session,
            media_id_or_shortcode=media_code,
            comment_text=text,
            client=self.client,
        )

    async def save(self, media_code: str) -> dict[str, Any]:
        return await save_media(
            self.session, media_id_or_shortcode=media_code, client=self.client
        )

    async def unsave(self, media_code: str) -> dict[str, Any]:
        return await save_media(
            self.session,
            media_id_or_shortcode=media_code,
            unsave=True,
            client=self.client,
        )

    # --- Notes ---

    async def post_note(self, text: str) -> dict[str, Any]:
        return await create_note(self.session, text=text, client=self.client)

    async def delete_note(self, note_id: int | str) -> dict[str, Any]:
        return await delete_note(self.session, note_id=note_id, client=self.client)

    async def get_notes(self) -> dict[str, Any]:
        return await fetch_notes(self.session, client=self.client)

    # --- Event Filter Routing ---

    def on(
        self,
        event_filter: Filter | None = None,
    ) -> Callable[[Callable[[dict[str, Any]], Any]], Callable[[dict[str, Any]], Any]]:
        """Decorator to register an event handler with optional Filter matching."""

        def decorator(
            func: Callable[[dict[str, Any]], Any],
        ) -> Callable[[dict[str, Any]], Any]:
            self._handlers.append((event_filter, func))
            return func

        return decorator

    async def dispatch_event(self, event: dict[str, Any]) -> None:
        """Route an inbound event through all registered filter handlers."""
        for flt, handler in self._handlers:
            if flt is None or flt(event):
                res = handler(event)
                if asyncio.iscoroutine(res):
                    await res


__all__ = [
    "IGClient",
]
