from __future__ import annotations


from igchat import filters


def test_text_filter():
    assert filters.text({"data": {"text": "hello"}})
    assert not filters.text({"data": {"text": ""}})
    assert not filters.text({"data": {}})


def test_command_filter():
    cmd_help = filters.command("help", prefixes=("/", "!"))
    assert cmd_help({"data": {"text": "/help me"}})
    assert cmd_help({"data": {"text": "!HELP"}})
    assert not cmd_help({"data": {"text": "/ping"}})
    assert not cmd_help({"data": {"text": "hello /help"}})


def test_regex_filter():
    pattern = filters.regex(r"^https://instagram\.com/reel/")
    assert pattern({"data": {"text": "https://instagram.com/reel/C12345"}})
    assert not pattern(
        {"data": {"text": "check out https://instagram.com/reel/C12345"}}
    )


def test_composable_and_or_invert():
    f_text = filters.text
    f_group = filters.group
    f_me = filters.sender("12345")

    f_combined = f_group & f_text & ~f_me

    # Group message with text from someone else -> True
    assert f_combined(
        {
            "data": {
                "is_group": True,
                "text": "Alo",
                "sender_id": "99999",
            }
        }
    )

    # Group message from me -> False
    assert not f_combined(
        {
            "data": {
                "is_group": True,
                "text": "Alo",
                "sender_id": "12345",
            }
        }
    )

    # DM message from someone else -> False
    assert not f_combined(
        {
            "data": {
                "is_group": False,
                "text": "Alo",
                "sender_id": "99999",
            }
        }
    )


def test_media_and_reaction_filters():
    assert filters.voice({"data": {"item_type": "voice_media"}})
    assert filters.photo({"data": {"item_type": "photo_media"}})
    assert filters.video({"data": {"item_type": "video_clip"}})
    assert filters.reaction({"type": "reaction", "data": {"emoji": "🔥"}})
    assert filters.silent({"data": {"text": "@silent chào buổi sáng"}})
