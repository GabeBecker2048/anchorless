from anchorless.text import (
    canonical_url,
    clean_headline,
    clean_text,
    is_filler,
    shorten,
    similarity,
    title_tokens,
)


def test_clean_text_strips_html_and_entities():
    assert clean_text("<p>Rock &amp;amp; roll</p>\n  now") == "Rock & roll now"


def test_canonical_url_drops_tracking():
    a = canonical_url("https://www.example.com/a/b/?utm_source=rss&id=3#top")
    b = canonical_url("http://example.com/a/b?id=3")
    assert a == b


def test_headline_decorations():
    assert clean_headline("Live updates: Storm hits coast") == "Storm hits coast"
    assert clean_headline("Storm hits coast – as it happened") == "Storm hits coast"
    assert clean_headline("Stocks rise: Live updates") == "Stocks rise"


def test_filler():
    assert is_filler("Here's the latest.")
    assert not is_filler("Pope visits Kenya")


def test_shorten_at_sentence():
    text = "First sentence here. Second sentence is long " + "x" * 50
    assert shorten(text, 36) == "First sentence here."
    assert shorten("word " * 20, 22).endswith("…")


def test_similarity():
    a = title_tokens("Senator hospitalized after stroke, aides say")
    b = title_tokens("Senator is hospitalized following a stroke")
    assert similarity(a, b) >= 0.5
    assert similarity(a, title_tokens("Stocks rally on earnings")) == 0
