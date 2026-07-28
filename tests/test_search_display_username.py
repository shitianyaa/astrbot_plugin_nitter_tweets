from media_support.html_backend.parser import parse_timeline_html
from rendering.tweets import TweetMessageRenderer
from shared.utils import TweetItem


def test_display_username_prefers_link_author_for_query_keys():
    tweet = TweetItem(
        text="body text here",
        link="https://x.com/AuthorName/status/42",
        published="",
    )
    assert TweetMessageRenderer.display_username("#tagquery", tweet) == "AuthorName"
    assert TweetMessageRenderer.display_username("q:#tagquery", tweet) == "AuthorName"
    assert TweetMessageRenderer.display_username("AuthorName", tweet) == "AuthorName"


def test_format_tweet_search_query_not_as_author():
    tweet = TweetItem(
        text="hello body",
        link="https://x.com/RealUser/status/99",
        published="",
    )
    text = TweetMessageRenderer.format_tweet(
        1, "#蔚蓝档案", tweet, omit_status_url=True
    )
    assert "@RealUser" in text
    assert "#蔚蓝档案" not in text.split("原文")[0]
    assert "hello body" in text


def test_format_tweet_telegram_header_has_explicit_link_not_query():
    tweet = TweetItem(
        text="visible body for link",
        link="https://x.com/RealUser/status/99",
        published="",
    )
    text = TweetMessageRenderer.format_tweet(
        1, "#tag", tweet, link_style="telegram_md", omit_status_url=True
    )
    assert text.startswith(
        "𝕏 · RealUser · [🔗 查看推文](https://x.com/RealUser/status/99)"
    )
    assert "visible body for link" in text
    assert not text.startswith("[#tag]")


def test_parse_timeline_extracts_body_and_username():
    html = """
    <div class="timeline-item ">
      <a class="tweet-link" href="/SomeUser/status/12345">x</a>
      <div class="tweet-content media-body" dir="auto">Hello <b>world</b></div>
    </div>
    """
    page = parse_timeline_html(html, "https://nitter.example")
    assert len(page.tweets) == 1
    assert page.tweets[0].username == "SomeUser"
    assert "Hello world" in page.tweets[0].text
    assert page.tweets[0].status_id == "12345"
