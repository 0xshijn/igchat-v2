"""
Đường dẫn file:
  src/_features/_instagram/_get_user_info.py

Mục đích:
  - Truy xuất thông tin (profile) của một người dùng bất kỳ.

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
from typing import Any

import httpx

from _core._utils import formAll, post_form_json_async

USER_INFO_URL = "https://www.instagram.com/api/graphql/"


def _build_request(dataIGS: dict[str, Any], userID: str | int) -> dict[str, Any]:
    data_form = formAll(
        dataIGS, "useIGDCreateOptimisticThreadUserQuery", 35274961328786258
    )
    data_form["variables"] = json.dumps(
        {"messaging_user_fbid": str(userID)},
        separators=(",", ":"),
    )
    data_form["ids[0]"] = str(userID)
    return data_form


def _build_username_search_request(
    dataIGS: dict[str, Any], username: str
) -> dict[str, Any]:
    clean = username.lstrip("@").strip()
    data_form = formAll(
        dataIGS, "IGDOmniPickerSearchResultsListQuery", 27248216181454285
    )
    data_form["variables"] = json.dumps(
        {"search_text": clean},
        separators=(",", ":"),
    )
    return data_form


def _build_profile_page_request(
    dataIGS: dict[str, Any], igid: str | int
) -> dict[str, Any]:
    data_form = formAll(dataIGS, "PolarisProfilePageContentQuery", 26672929172408668)
    data_form["variables"] = json.dumps(
        {
            "enable_integrity_filters": True,
            "id": str(igid),
            "__relay_internal__pv__PolarisCannesGuardianExperienceEnabledrelayprovider": True,
            "__relay_internal__pv__PolarisCASB976ProfileEnabledrelayprovider": False,
            "__relay_internal__pv__PolarisWebSchoolsEnabledrelayprovider": False,
            "__relay_internal__pv__PolarisRepostsConsumptionEnabledrelayprovider": False,
        },
        separators=(",", ":"),
    )
    return data_form


def _format_ig_user_dict(
    ig_user: dict[str, Any], fallback_id: str | int
) -> dict[str, Any]:
    username = ig_user.get("username")
    full_name = ig_user.get("full_name") or username
    first_name = (
        str(full_name).split()[0]
        if isinstance(full_name, str) and full_name.strip()
        else username
    )
    result: dict[str, Any] = {
        "idUser": str(
            ig_user.get("interop_messaging_user_fbid")
            or ig_user.get("id")
            or ig_user.get("pk")
            or fallback_id
        ),
        "nameUser": full_name,
        "firstName": first_name,
        "Username": username,
        "thumbSrc": ig_user.get("profile_pic_url"),
        "urlProfile": (f"https://www.instagram.com/{username}/" if username else None),
        "genderUser": "Unknown (Không xác định)",
        "alternateName": None,
        "chatWithUSerIsNonFriend": not bool(
            (ig_user.get("friendship_status") or {}).get("following")
        ),
    }
    if "biography" in ig_user:
        result["biography"] = ig_user.get("biography")
    if "follower_count" in ig_user:
        result["followerCount"] = ig_user.get("follower_count")
    if "following_count" in ig_user:
        result["followingCount"] = ig_user.get("following_count")
    if "media_count" in ig_user:
        result["mediaCount"] = ig_user.get("media_count")
    if "is_verified" in ig_user:
        result["isVerified"] = bool(ig_user.get("is_verified"))
    if "is_private" in ig_user:
        result["isPrivate"] = bool(ig_user.get("is_private"))
    return result


def _parse_response(payload: dict[str, Any], userID: str | int) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload, dict) else None
    ig_user = (
        data.get("xig_user_from_messaging_user_fbid") or data.get("user")
        if isinstance(data, dict)
        else None
    )
    if isinstance(ig_user, dict):
        return _format_ig_user_dict(ig_user, userID)

    if isinstance(data, dict) and "xfb_combinedIGSearchQuery" in data:
        combined = data.get("xfb_combinedIGSearchQuery") or {}
        contacts = (
            combined.get("search_messenger_contact_v2")
            if isinstance(combined, dict)
            else None
        )
        target_clean = str(userID).lstrip("@").strip().lower()
        if isinstance(contacts, list) and contacts:
            matched = next(
                (
                    c
                    for c in contacts
                    if isinstance(c, dict)
                    and str(c.get("username") or "").lower() == target_clean
                ),
                contacts[0] if isinstance(contacts[0], dict) else None,
            )
            if isinstance(matched, dict):
                return _format_ig_user_dict(matched, userID)

    profiles = (payload.get("payload") or {}).get("profiles") or {}
    profile = profiles.get(str(userID))
    if not isinstance(profile, dict):
        return {
            "error": 1,
            "messages": "Không tìm thấy hồ sơ người dùng trong response.",
        }

    raw_gender = profile.get("gender")
    gender = raw_gender if isinstance(raw_gender, int) else None
    gender_labels = {1: "Female (Nữ)", 2: "Male (Nam)"}
    gender_label = (
        gender_labels.get(gender, "Unknown (Không xác định)")
        if gender is not None
        else "Unknown (Không xác định)"
    )
    return {
        "idUser": profile.get("id"),
        "nameUser": profile.get("name"),
        "firstName": profile.get("firstName"),
        "Username": profile.get("vanity"),
        "thumbSrc": profile.get("thumbSrc")
        or profile.get("thumb_src")
        or profile.get("thumnSrc"),
        "urlProfile": profile.get("uri"),
        "genderUser": gender_label,
        "alternateName": profile.get("alternateName"),
        "chatWithUSerIsNonFriend": profile.get("is_nonfriend_messenger_contact"),
    }


async def func(
    dataIGS: dict[str, Any],
    userID: str | int,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    try:
        user_str = str(userID).strip()
        is_username = bool(user_str) and not user_str.lstrip("@").isdigit()
        form_data = (
            _build_username_search_request(dataIGS, user_str)
            if is_username
            else _build_request(dataIGS, userID)
        )
        payload = await post_form_json_async(
            USER_INFO_URL,
            form_data,
            dataIGS["cookieIGS"],
            strip_for_loop_prefix=True,
            client=client,
        )
        parsed = _parse_response(payload, userID)
        if not is_username and (
            parsed.get("error")
            or parsed.get("Username")
            in {None, "", "Người dùng Instagram"}
            and parsed.get("nameUser")
            in {None, "", "Người dùng Instagram"}
        ):
            prof_payload = await post_form_json_async(
                USER_INFO_URL,
                _build_profile_page_request(dataIGS, userID),
                dataIGS["cookieIGS"],
                strip_for_loop_prefix=True,
                client=client,
            )
            prof_parsed = _parse_response(prof_payload, userID)
            if not prof_parsed.get("error"):
                return prof_parsed
        return parsed
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        return {"error": 1, "messages": str(exc)}
