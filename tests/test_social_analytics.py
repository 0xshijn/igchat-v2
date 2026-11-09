from __future__ import annotations


from igchat.social.analytics import analyze_relationships


def test_analyze_relationships():
    following = ["alice", "bob", "charlie", "david"]
    followers = ["bob", "charlie", "eve", "frank"]

    analytics = analyze_relationships(following, followers)

    assert analytics.unrequited == ["alice", "david"]
    assert analytics.fans == ["eve", "frank"]
    assert analytics.mutual == ["bob", "charlie"]
    assert analytics.total_unrequited == 2
    assert analytics.total_fans == 2
    assert analytics.total_mutual == 2
