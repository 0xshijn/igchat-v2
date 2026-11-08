"""API mức cao cho các JSON-RPC action của bridge E2EE."""

from __future__ import annotations

import base64
from typing import Any

from _messaging._listening_e2ee import _BridgeProcess
from _messaging._send_e2ee import normalize_chat_jid


class BridgeActions:
    def __init__(self, bridge: _BridgeProcess) -> None:
        self._bridge = bridge

    def _call_blocking(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return self._bridge.call_blocking(method, params)

    async def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return await self._bridge.call(method, params)

    def edit_message_blocking(self, message_id: str, new_text: str) -> dict[str, Any]:
        return self._call_blocking(
            "editMessage", {"messageId": message_id, "newText": new_text}
        )

    async def edit_message(self, message_id: str, new_text: str) -> dict[str, Any]:
        return await self._call(
            "editMessage", {"messageId": message_id, "newText": new_text}
        )

    def unsend_message_blocking(self, message_id: str) -> dict[str, Any]:
        return self._call_blocking("unsendMessage", {"messageId": message_id})

    async def unsend_message(self, message_id: str) -> dict[str, Any]:
        return await self._call("unsendMessage", {"messageId": message_id})

    @staticmethod
    def _e2ee_message_params(
        chat_jid: str, message_id: str, new_text: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "chatJid": normalize_chat_jid(chat_jid),
            "messageId": message_id,
        }
        if new_text is not None:
            params["newText"] = new_text
        return params

    def edit_e2ee_message_blocking(
        self, chat_jid: str, message_id: str, new_text: str
    ) -> dict[str, Any]:
        return self._call_blocking(
            "editE2EEMessage",
            self._e2ee_message_params(chat_jid, message_id, new_text),
        )

    async def edit_e2ee_message(
        self, chat_jid: str, message_id: str, new_text: str
    ) -> dict[str, Any]:
        return await self._call(
            "editE2EEMessage",
            self._e2ee_message_params(chat_jid, message_id, new_text),
        )

    def unsend_e2ee_message_blocking(
        self, chat_jid: str, message_id: str
    ) -> dict[str, Any]:
        return self._call_blocking(
            "unsendE2EEMessage", self._e2ee_message_params(chat_jid, message_id)
        )

    async def unsend_e2ee_message(
        self, chat_jid: str, message_id: str
    ) -> dict[str, Any]:
        return await self._call(
            "unsendE2EEMessage", self._e2ee_message_params(chat_jid, message_id)
        )

    def send_typing_indicator_blocking(
        self,
        thread_id: int,
        is_typing: bool,
        is_group: bool = False,
        thread_type: int = 1,
    ) -> dict[str, Any]:
        return self._call_blocking(
            "sendTypingIndicator",
            {
                "threadId": thread_id,
                "isTyping": is_typing,
                "isGroup": is_group,
                "threadType": thread_type,
            },
        )

    async def send_typing_indicator(
        self,
        thread_id: int,
        is_typing: bool,
        is_group: bool = False,
        thread_type: int = 1,
    ) -> dict[str, Any]:
        return await self._call(
            "sendTypingIndicator",
            {
                "threadId": thread_id,
                "isTyping": is_typing,
                "isGroup": is_group,
                "threadType": thread_type,
            },
        )

    def mark_read_blocking(self, thread_id: int, watermark_ts: int) -> dict[str, Any]:
        return self._call_blocking(
            "markRead", {"threadId": thread_id, "watermarkTs": watermark_ts}
        )

    async def mark_read(self, thread_id: int, watermark_ts: int) -> dict[str, Any]:
        return await self._call(
            "markRead", {"threadId": thread_id, "watermarkTs": watermark_ts}
        )

    def send_e2ee_typing_blocking(
        self, chat_jid: str, is_typing: bool
    ) -> dict[str, Any]:
        return self._call_blocking(
            "sendE2EETyping",
            {"chatJid": normalize_chat_jid(chat_jid), "isTyping": is_typing},
        )

    async def send_e2ee_typing(self, chat_jid: str, is_typing: bool) -> dict[str, Any]:
        return await self._call(
            "sendE2EETyping",
            {"chatJid": normalize_chat_jid(chat_jid), "isTyping": is_typing},
        )

    @staticmethod
    def _audio_params(
        chat_jid: str,
        data: bytes,
        mime_type: str,
        duration: int,
        ptt: bool,
        reply_to_id: str,
        reply_to_sender_jid: str,
    ) -> dict[str, Any]:
        return {
            "chatJid": normalize_chat_jid(chat_jid),
            "data": base64.b64encode(data).decode("ascii"),
            "mimeType": mime_type,
            "duration": duration,
            "ptt": ptt,
            "replyToId": reply_to_id,
            "replyToSenderJid": reply_to_sender_jid,
        }

    def send_e2ee_audio_blocking(
        self,
        chat_jid: str,
        data: bytes,
        mime_type: str = "audio/ogg; codecs=opus",
        duration: int = 0,
        ptt: bool = True,
        reply_to_id: str = "",
        reply_to_sender_jid: str = "",
    ) -> dict[str, Any]:
        return self._call_blocking(
            "sendE2EEAudio",
            self._audio_params(
                chat_jid,
                data,
                mime_type,
                duration,
                ptt,
                reply_to_id,
                reply_to_sender_jid,
            ),
        )

    async def send_e2ee_audio(
        self,
        chat_jid: str,
        data: bytes,
        mime_type: str = "audio/ogg; codecs=opus",
        duration: int = 0,
        ptt: bool = True,
        reply_to_id: str = "",
        reply_to_sender_jid: str = "",
    ) -> dict[str, Any]:
        return await self._call(
            "sendE2EEAudio",
            self._audio_params(
                chat_jid,
                data,
                mime_type,
                duration,
                ptt,
                reply_to_id,
                reply_to_sender_jid,
            ),
        )

    @staticmethod
    def _image_params(
        chat_jid: str,
        data: bytes,
        mime_type: str,
        caption: str,
        width: int,
        height: int,
        reply_to_id: str,
        reply_to_sender_jid: str,
    ) -> dict[str, Any]:
        return {
            "chatJid": normalize_chat_jid(chat_jid),
            "data": base64.b64encode(data).decode("ascii"),
            "mimeType": mime_type,
            "caption": caption,
            "width": width,
            "height": height,
            "replyToId": reply_to_id,
            "replyToSenderJid": reply_to_sender_jid,
        }

    def send_e2ee_image_blocking(
        self,
        chat_jid: str,
        data: bytes,
        mime_type: str = "image/jpeg",
        caption: str = "",
        width: int = 0,
        height: int = 0,
        reply_to_id: str = "",
        reply_to_sender_jid: str = "",
    ) -> dict[str, Any]:
        return self._call_blocking(
            "sendE2EEImage",
            self._image_params(
                chat_jid,
                data,
                mime_type,
                caption,
                width,
                height,
                reply_to_id,
                reply_to_sender_jid,
            ),
        )

    async def send_e2ee_image(
        self,
        chat_jid: str,
        data: bytes,
        mime_type: str = "image/jpeg",
        caption: str = "",
        width: int = 0,
        height: int = 0,
        reply_to_id: str = "",
        reply_to_sender_jid: str = "",
    ) -> dict[str, Any]:
        return await self._call(
            "sendE2EEImage",
            self._image_params(
                chat_jid,
                data,
                mime_type,
                caption,
                width,
                height,
                reply_to_id,
                reply_to_sender_jid,
            ),
        )

    def download_media_blocking(self, url: str) -> bytes:
        result = self._call_blocking("downloadMedia", {"url": url})
        return base64.b64decode(result["data"], validate=True)

    async def download_media(self, url: str) -> bytes:
        result = await self._call("downloadMedia", {"url": url})
        return base64.b64decode(result["data"], validate=True)

    @staticmethod
    def _download_e2ee_params(
        direct_path: str,
        media_key: str,
        media_sha256: str,
        media_enc_sha256: str,
        media_type: str,
        mime_type: str,
        file_size: int,
    ) -> dict[str, Any]:
        return {
            "directPath": direct_path,
            "mediaKey": media_key,
            "mediaSha256": media_sha256,
            "mediaEncSha256": media_enc_sha256,
            "mediaType": media_type,
            "mimeType": mime_type,
            "fileSize": file_size,
        }

    @staticmethod
    def _decode_media_result(result: dict[str, Any]) -> dict[str, Any]:
        if isinstance(result.get("data"), str):
            result = dict(result)
            result["data"] = base64.b64decode(result["data"], validate=True)
        return result

    def download_e2ee_media_blocking(
        self,
        direct_path: str,
        media_key: str,
        media_sha256: str,
        media_enc_sha256: str,
        media_type: str,
        mime_type: str,
        file_size: int,
    ) -> dict[str, Any]:
        result = self._call_blocking(
            "downloadE2EEMedia",
            self._download_e2ee_params(
                direct_path,
                media_key,
                media_sha256,
                media_enc_sha256,
                media_type,
                mime_type,
                file_size,
            ),
        )
        return self._decode_media_result(result)

    async def download_e2ee_media(
        self,
        direct_path: str,
        media_key: str,
        media_sha256: str,
        media_enc_sha256: str,
        media_type: str,
        mime_type: str,
        file_size: int,
    ) -> dict[str, Any]:
        result = await self._call(
            "downloadE2EEMedia",
            self._download_e2ee_params(
                direct_path,
                media_key,
                media_sha256,
                media_enc_sha256,
                media_type,
                mime_type,
                file_size,
            ),
        )
        return self._decode_media_result(result)

    def pin_message_blocking(self, thread_id: int, message_id: str) -> dict[str, Any]:
        return self._call_blocking(
            "pinMessage", {"threadId": thread_id, "messageId": message_id}
        )

    async def pin_message(self, thread_id: int, message_id: str) -> dict[str, Any]:
        return await self._call(
            "pinMessage", {"threadId": thread_id, "messageId": message_id}
        )

    def unpin_message_blocking(self, thread_id: int, message_id: str) -> dict[str, Any]:
        return self._call_blocking(
            "unpinMessage", {"threadId": thread_id, "messageId": message_id}
        )

    async def unpin_message(self, thread_id: int, message_id: str) -> dict[str, Any]:
        return await self._call(
            "unpinMessage", {"threadId": thread_id, "messageId": message_id}
        )

    def pin_thread_blocking(self, thread_id: int, pin: bool = True) -> dict[str, Any]:
        return self._call_blocking("pinThread", {"threadId": thread_id, "pin": pin})

    async def pin_thread(self, thread_id: int, pin: bool = True) -> dict[str, Any]:
        return await self._call("pinThread", {"threadId": thread_id, "pin": pin})

    def mute_thread_blocking(
        self, thread_id: int, mute_seconds: int = -1
    ) -> dict[str, Any]:
        return self._call_blocking(
            "muteThread", {"threadId": thread_id, "muteSeconds": mute_seconds}
        )

    async def mute_thread(
        self, thread_id: int, mute_seconds: int = -1
    ) -> dict[str, Any]:
        return await self._call(
            "muteThread", {"threadId": thread_id, "muteSeconds": mute_seconds}
        )

    def rename_thread_blocking(self, thread_id: int, new_name: str) -> dict[str, Any]:
        return self._call_blocking(
            "renameThread", {"threadId": thread_id, "newName": new_name}
        )

    async def rename_thread(self, thread_id: int, new_name: str) -> dict[str, Any]:
        return await self._call(
            "renameThread", {"threadId": thread_id, "newName": new_name}
        )

    def delete_thread_blocking(
        self, thread_id: int, *, mark_as_spam: bool = False
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"threadId": thread_id}
        if mark_as_spam:
            params["markAsSpam"] = True
        return self._call_blocking("deleteThread", params)

    async def delete_thread(
        self, thread_id: int, *, mark_as_spam: bool = False
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"threadId": thread_id}
        if mark_as_spam:
            params["markAsSpam"] = True
        return await self._call("deleteThread", params)

    def accept_message_request_blocking(self, thread_id: int) -> dict[str, Any]:
        return self._call_blocking("acceptMessageRequest", {"threadId": thread_id})

    async def accept_message_request(self, thread_id: int) -> dict[str, Any]:
        return await self._call("acceptMessageRequest", {"threadId": thread_id})

    def search_users_blocking(self, query: str) -> list[dict[str, Any]]:
        res = self._call_blocking("searchUsers", {"query": query})
        users = res.get("users")
        return users if isinstance(users, list) else []

    async def search_users(self, query: str) -> list[dict[str, Any]]:
        res = await self._call("searchUsers", {"query": query})
        users = res.get("users")
        return users if isinstance(users, list) else []

    def get_user_info_blocking(self, user_id: int) -> dict[str, Any]:
        return self._call_blocking("getUserInfo", {"userId": user_id})

    async def get_user_info(self, user_id: int) -> dict[str, Any]:
        return await self._call("getUserInfo", {"userId": user_id})

    def get_inbox_blocking(self) -> list[dict[str, Any]]:
        res = self._call_blocking("getInbox", {})
        threads = res.get("threads")
        return threads if isinstance(threads, list) else []

    async def get_inbox(self) -> list[dict[str, Any]]:
        res = await self._call("getInbox", {})
        threads = res.get("threads")
        return threads if isinstance(threads, list) else []

    def get_thread_info_blocking(
        self, thread_id: int, message_limit: int = 10
    ) -> dict[str, Any]:
        return self._call_blocking(
            "getThreadInfo",
            {"threadId": thread_id, "messageLimit": message_limit},
        )

    async def get_thread_info(
        self, thread_id: int, message_limit: int = 10
    ) -> dict[str, Any]:
        return await self._call(
            "getThreadInfo",
            {"threadId": thread_id, "messageLimit": message_limit},
        )

    def get_message_requests_blocking(self) -> list[dict[str, Any]]:
        res = self._call_blocking("getMessageRequests", {})
        threads = res.get("threads")
        return threads if isinstance(threads, list) else []

    async def get_message_requests(self) -> list[dict[str, Any]]:
        res = await self._call("getMessageRequests", {})
        threads = res.get("threads")
        return threads if isinstance(threads, list) else []

    def send_media_from_url_blocking(
        self,
        thread_id: int,
        url: str,
        *,
        filename: str = "",
        mime_type: str = "",
        reply_to_id: str = "",
        is_voice: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"threadId": thread_id, "url": url}
        if filename:
            params["filename"] = filename
        if mime_type:
            params["mimeType"] = mime_type
        if reply_to_id:
            params["replyToId"] = reply_to_id
        if is_voice:
            params["isVoice"] = True
        return self._call_blocking("sendMediaFromURL", params)

    async def send_media_from_url(
        self,
        thread_id: int,
        url: str,
        *,
        filename: str = "",
        mime_type: str = "",
        reply_to_id: str = "",
        is_voice: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"threadId": thread_id, "url": url}
        if filename:
            params["filename"] = filename
        if mime_type:
            params["mimeType"] = mime_type
        if reply_to_id:
            params["replyToId"] = reply_to_id
        if is_voice:
            params["isVoice"] = True
        return await self._call("sendMediaFromURL", params)

    def send_voice_from_url_blocking(
        self,
        thread_id: int,
        url: str,
        *,
        reply_to_id: str = "",
    ) -> dict[str, Any]:
        return self.send_media_from_url_blocking(
            thread_id, url, reply_to_id=reply_to_id, is_voice=True
        )

    async def send_voice_from_url(
        self,
        thread_id: int,
        url: str,
        *,
        reply_to_id: str = "",
    ) -> dict[str, Any]:
        return await self.send_media_from_url(
            thread_id, url, reply_to_id=reply_to_id, is_voice=True
        )

    def create_group_blocking(
        self, user_ids: list[int], title: str = ""
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"userIds": user_ids}
        if title:
            params["title"] = title
        return self._call_blocking("createGroup", params)

    async def create_group(
        self, user_ids: list[int], title: str = ""
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"userIds": user_ids}
        if title:
            params["title"] = title
        return await self._call("createGroup", params)

    def add_group_members_blocking(
        self, thread_id: int, user_ids: list[int]
    ) -> dict[str, Any]:
        return self._call_blocking(
            "addGroupMembers", {"threadId": thread_id, "userIds": user_ids}
        )

    async def add_group_members(
        self, thread_id: int, user_ids: list[int]
    ) -> dict[str, Any]:
        return await self._call(
            "addGroupMembers", {"threadId": thread_id, "userIds": user_ids}
        )

    def remove_group_member_blocking(
        self, thread_id: int, user_id: int
    ) -> dict[str, Any]:
        return self._call_blocking(
            "removeGroupMember", {"threadId": thread_id, "userId": user_id}
        )

    async def remove_group_member(self, thread_id: int, user_id: int) -> dict[str, Any]:
        return await self._call(
            "removeGroupMember", {"threadId": thread_id, "userId": user_id}
        )

    def modify_group_admins_blocking(
        self, thread_id: int, user_ids: list[int], *, promote: bool = True
    ) -> dict[str, Any]:
        return self._call_blocking(
            "modifyGroupAdmins",
            {"threadId": thread_id, "userIds": user_ids, "promote": promote},
        )

    async def modify_group_admins(
        self, thread_id: int, user_ids: list[int], *, promote: bool = True
    ) -> dict[str, Any]:
        return await self._call(
            "modifyGroupAdmins",
            {"threadId": thread_id, "userIds": user_ids, "promote": promote},
        )

    def leave_group_blocking(self, thread_id: int) -> dict[str, Any]:
        return self._call_blocking("leaveGroup", {"threadId": thread_id})

    async def leave_group(self, thread_id: int) -> dict[str, Any]:
        return await self._call("leaveGroup", {"threadId": thread_id})

    def set_user_blocked_blocking(
        self, user_id: str | int, *, blocked: bool = True
    ) -> dict[str, Any]:
        return self._call_blocking(
            "setUserBlocked", {"userId": str(user_id), "blocked": blocked}
        )

    async def set_user_blocked(
        self, user_id: str | int, *, blocked: bool = True
    ) -> dict[str, Any]:
        return await self._call(
            "setUserBlocked", {"userId": str(user_id), "blocked": blocked}
        )

    def fetch_media_blocking(self, input_str: str) -> dict[str, Any]:
        return self._call_blocking("fetchMedia", {"input": input_str})

    async def fetch_media(self, input_str: str) -> dict[str, Any]:
        return await self._call("fetchMedia", {"input": input_str})

    def edit_group_avatar_blocking(
        self, thread_id: int, image_url: str = ""
    ) -> dict[str, Any]:
        return self._call_blocking(
            "editGroupAvatar", {"threadId": thread_id, "imageUrl": image_url}
        )

    async def edit_group_avatar(
        self, thread_id: int, image_url: str = ""
    ) -> dict[str, Any]:
        return await self._call(
            "editGroupAvatar", {"threadId": thread_id, "imageUrl": image_url}
        )

    def forward_message_blocking(
        self,
        source_thread_id: int,
        target_thread_id: int,
        message_id: str = "",
        text: str = "",
    ) -> dict[str, Any]:
        return self._call_blocking(
            "forwardMessage",
            {
                "sourceThreadId": source_thread_id,
                "targetThreadId": target_thread_id,
                "messageId": message_id,
                "text": text,
            },
        )

    async def forward_message(
        self,
        source_thread_id: int,
        target_thread_id: int,
        message_id: str = "",
        text: str = "",
    ) -> dict[str, Any]:
        return await self._call(
            "forwardMessage",
            {
                "sourceThreadId": source_thread_id,
                "targetThreadId": target_thread_id,
                "messageId": message_id,
                "text": text,
            },
        )

    def get_web_profile_blocking(self, identifier: str) -> dict[str, Any]:
        return self._call_blocking("getWebProfile", {"identifier": str(identifier)})

    async def get_web_profile(self, identifier: str) -> dict[str, Any]:
        return await self._call("getWebProfile", {"identifier": str(identifier)})

    def fetch_stories_blocking(self, identifier: str) -> dict[str, Any]:
        return self._call_blocking("fetchStories", {"identifier": str(identifier)})

    async def fetch_stories(self, identifier: str) -> dict[str, Any]:
        return await self._call("fetchStories", {"identifier": str(identifier)})

    def paginate_inbox_blocking(
        self, cursor: str = "", folder: str = "INBOX"
    ) -> dict[str, Any]:
        return self._call_blocking(
            "paginateInbox", {"cursor": cursor, "folder": folder}
        )

    async def paginate_inbox(
        self, cursor: str = "", folder: str = "INBOX"
    ) -> dict[str, Any]:
        return await self._call("paginateInbox", {"cursor": cursor, "folder": folder})

    def paginate_messages_blocking(
        self, thread_id: int, cursor: str = "", limit: int = 20
    ) -> dict[str, Any]:
        return self._call_blocking(
            "paginateMessages",
            {"threadId": thread_id, "cursor": cursor, "limit": limit},
        )

    async def paginate_messages(
        self, thread_id: int, cursor: str = "", limit: int = 20
    ) -> dict[str, Any]:
        return await self._call(
            "paginateMessages",
            {"threadId": thread_id, "cursor": cursor, "limit": limit},
        )

    def send_message_with_mentions_blocking(
        self,
        thread_id: int,
        text: str,
        mention_ids: list[int] | None = None,
        mention_offsets: list[int] | None = None,
        mention_lengths: list[int] | None = None,
        reply_to_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "threadId": thread_id,
            "text": text,
            "mentionIds": mention_ids or [],
            "mentionOffsets": mention_offsets or [],
            "mentionLengths": mention_lengths or [],
        }
        if reply_to_id:
            params["replyToId"] = reply_to_id
        return self._call_blocking("sendMessage", params)

    async def send_message_with_mentions(
        self,
        thread_id: int,
        text: str,
        mention_ids: list[int] | None = None,
        mention_offsets: list[int] | None = None,
        mention_lengths: list[int] | None = None,
        reply_to_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "threadId": thread_id,
            "text": text,
            "mentionIds": mention_ids or [],
            "mentionOffsets": mention_offsets or [],
            "mentionLengths": mention_lengths or [],
        }
        if reply_to_id:
            params["replyToId"] = reply_to_id
        return await self._call("sendMessage", params)

    def get_unread_count_blocking(self) -> dict[str, Any]:
        return self._call_blocking("getUnreadCount", {})

    async def get_unread_count(self) -> dict[str, Any]:
        return await self._call("getUnreadCount", {})


