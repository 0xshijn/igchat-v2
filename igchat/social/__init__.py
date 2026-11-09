"""Instagram social APIs: profiles, friendships, analytics, posts/stories & search."""

from __future__ import annotations

from .analytics import (
    FollowerAnalytics,
    analyze_relationships,
    fetch_close_friends,
    fetch_story_viewers,
    update_close_friends,
)
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
    "FollowerAnalytics",
    "analyze_relationships",
    "block_user",
    "change_bio",
    "comment_media",
    "delete_comment",
    "fetch_close_friends",
    "fetch_notifications",
    "fetch_story_viewers",
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
    "update_close_friends",
]
