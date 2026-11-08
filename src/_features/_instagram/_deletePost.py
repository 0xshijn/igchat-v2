"""
Đường dẫn file:
  src/_features/_instagram/_deletePost.py

Mục đích:
  - Xoá bài viết trên dòng thời gian bằng cách đưa vào thùng rác.

Cách hoạt động:
  - Nạp dependency/guard cần thiết, thực hiện các async HTTP requests tới API nội bộ hoặc GraphQL của Instagram.
  - Các thao tác request đều phải thông qua httpx.AsyncClient và module _core._utils để bảo đảm an toàn kết nối.
  - Payload gửi đi/nhận về được xử lý JSON cẩn thận, bắt lỗi try-except đầy đủ để tránh crash hệ thống.

File liên quan:
  - src/main.py và các entrypoint khác.
  - Phụ thuộc vào _core._session, _core._utils để khởi tạo và thao tác HTTP.

Author: Shiin (Phước Toàn)
"""

from __future__ import annotations

import json
import base64
from typing import Any

import httpx

from _core._utils import formAll, post_form_json_async

_URL = "https://www.instagram.com/api/graphql/"
_DOC_ID = 26146132388368957


def _build_form(
    dataIGS: dict[str, Any], postID: str, typePost: str = "my_post"
) -> dict[str, Any]:
    if not str(postID).strip():
        raise ValueError("ID bài viết không được để trống.")
    """
        my_post = những bài viết của chính bản thân bạn viết nên (không phải share)
        others = phần còn lại, những bài viết của người khác, hoặc bài viết share từ người khác
    """
    if typePost == "my_post":
        postID_Params = f"S:_I1054626957723036:{postID}"
    else:
        postID_Params = f"S:_I{dataIGS['IGSID']}:{postID}:{postID}"
    PostID_Base64 = base64.b64encode(postID_Params.encode()).decode()
    data_form = formAll(dataIGS, "useCometTrashPostMutation", _DOC_ID)
    data_form["variables"] = json.dumps(
        {
            "input": {
                "story_id": PostID_Base64,
                "story_location": "TIMELINE",
                "actor_id": dataIGS["IGSID"],
                "client_mutation_id": "1",
            }
        },
        separators=(",", ":"),
    )

    return data_form


def _parse_result(payload: dict[str, Any]) -> dict[str, Any]:
    if (
        payload.get("status") == "ok" or payload.get("did_delete") is True
    ) and not payload.get("errors"):
        return {"success": 1, "messages": "Xóa bài viết thành công!"}
    errors = payload.get("errors") or []
    message = (
        errors[0].get("message") if errors and isinstance(errors[0], dict) else None
    )
    try:
        status = payload["data"]["move_to_trash_story"]["success"]
    except (KeyError, TypeError):
        status = False
    if errors or not status:
        return {
            "error": 1,
            "messages": message or "Instagram không phản hồi hợp lệ.",
        }
    return {"success": 1, "messages": "Xóa bài viết thành công!"}


async def func(
    dataIGS: dict[str, Any],
    postID: str,
    typePost: str = "my_post",
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    payload = await post_form_json_async(
        _URL,
        _build_form(dataIGS, postID, typePost),
        dataIGS["cookieIGS"],
        client=client,
    )
    return _parse_result(payload)


async def comment_instagram_media(
    dataIGS: dict[str, Any],
    post_or_url: str | int,
    comment_text: str,
    *,
    replied_to_comment_id: str | int | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Đăng bình luận (comment) lên bài viết hoặc Reel Instagram qua REST API Web v1."""
    from _features._instagram._reactionPost import shortcode_to_media_id

    text = str(comment_text).strip()
    if not text:
        return {"error": 1, "messages": "Nội dung bình luận không được để trống."}
    try:
        media_id = shortcode_to_media_id(post_or_url)
        form_data: dict[str, Any] = {"comment_text": text}
        if replied_to_comment_id:
            form_data["replied_to_comment_id"] = str(replied_to_comment_id)
        payload = await post_form_json_async(
            f"https://www.instagram.com/api/v1/web/comments/{media_id}/add/",
            form_data,
            dataIGS["cookieIGS"],
            client=client,
        )
        if payload.get("status") == "ok":
            return {
                "success": 1,
                "mediaId": media_id,
                "commentId": str(payload.get("id") or ""),
                "text": str(payload.get("text") or text),
                "messages": "Đăng bình luận thành công!",
            }
        return {
            "error": 1,
            "messages": str(
                payload.get("message") or "Instagram từ chối đăng bình luận."
            ),
        }
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        return {"error": 1, "messages": str(exc)}


async def delete_instagram_comment(
    dataIGS: dict[str, Any],
    post_or_url: str | int,
    comment_id: str | int,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Xóa bình luận trên bài viết hoặc Reel Instagram."""
    from _features._instagram._reactionPost import shortcode_to_media_id

    cid = str(comment_id).strip()
    if not cid:
        return {"error": 1, "messages": "comment_id không được để trống."}
    try:
        media_id = shortcode_to_media_id(post_or_url)
        payload = await post_form_json_async(
            f"https://www.instagram.com/api/v1/web/comments/{media_id}/delete/{cid}/",
            {},
            dataIGS["cookieIGS"],
            client=client,
        )
        if payload.get("status") == "ok":
            return {
                "success": 1,
                "mediaId": media_id,
                "commentId": cid,
                "messages": "Xóa bình luận thành công!",
            }
        return {
            "error": 1,
            "messages": str(
                payload.get("message") or "Instagram từ chối xóa bình luận."
            ),
        }
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        return {"error": 1, "messages": str(exc)}

