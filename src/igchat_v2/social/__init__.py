"""Instagram social APIs: profiles, friendships, posts/stories, search & inbox news."""

from __future__ import annotations

from .friendships import (
    block_user,
    follow_user,
    remove_follower,
    unblock_user,
    unfollow_user,
)
from .notifications import fetch_notifications
from .posts import (
    comment_media,
    delete_comment,
    like_media,
    media_id_to_shortcode,
    publish_photo,
    save_media,
    shortcode_to_media_id,
)
from .profile import change_bio, get_user_profile
from .search import search_users

__all__ = [
    "block_user",
    "change_bio",
    "comment_media",
    "delete_comment",
    "fetch_notifications",
    "follow_user",
    "get_user_profile",
    "like_media",
    "media_id_to_shortcode",
    "publish_photo",
    "remove_follower",
    "save_media",
    "search_users",
    "shortcode_to_media_id",
    "unblock_user",
    "unfollow_user",
]
