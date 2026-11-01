"""Cleaning up feed text, URLs and headlines."""

from __future__ import annotations

import hashlib
import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_WORD = re.compile(r"[a-z0-9]+")

# Query parameters that only track the click, not identify the article.
_TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|mc_cid|mc_eid|cmpid|ref|src|source|taid|ftag|cid|"
                       r"partner|ocid|rss|feed|traffic_source|at_.*|__.*)$", re.I)

_STOPWORDS = frozenset("""
a an and are as at be been but by for from has have he her his how in into is it its of
on or our over says say said she than that the their them they this to up was we were
what when where which who why will with after before about new more not no just you
your amid could would should may can s t
""".split())


def clean_text(value: str | None) -> str:
    """Feed HTML to one line of plain text."""
    if not value:
        return ""
    text = _TAG.sub(" ", value)
    text = html.unescape(html.unescape(text))
    return _SPACE.sub(" ", text).strip()


# Live-blog decorations that add nothing on a TV page.
_PREFIX = re.compile(
    r"^(live updates?|live|breaking news|breaking|watch|listen|video|opinion|analysis)\s*[:|–—-]\s*", re.I)
_SUFFIX = re.compile(
    r"\s*[-–—|:]\s*(follow live|live updates?|as it happened|live|video|photos?|watch)\s*$", re.I)
# Headlines made only of these words are not stories ("Here's the latest.").
_FILLER = frozenset("""
here latest live update news watch morning evening night briefing today week weekend
biggest missed top stories headlines know need
""".split())


def clean_headline(title: str) -> str:
    """Strip "Live updates:"-style decorations. "BREAKING:" is detected before this."""
    out = _SUFFIX.sub("", _PREFIX.sub("", title)).strip()
    return out[:1].upper() + out[1:] if out else title


def is_filler(title: str) -> bool:
    tokens = title_tokens(title)
    return not tokens or tokens <= _FILLER


def shorten(text: str, limit: int) -> str:
    """Cut at a sentence end (or a word) at or before ``limit`` characters."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    if end >= limit * 0.5:
        return cut[: end + 1]
    space = cut.rfind(" ")
    return (cut[:space] if space > 0 else cut).rstrip(",;:-") + "…"


def canonical_url(url: str) -> str:
    """The same article linked from two feeds should give the same string."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    host = parts.netloc.lower().removeprefix("www.")
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if not _TRACKING.match(k)))
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, query, ""))


def story_key(url: str, title: str) -> str:
    basis = canonical_url(url) if url else "title:" + title.lower()
    return hashlib.sha1(basis.encode()).hexdigest()[:16]


def _stem(word: str) -> str:
    # Just enough to match "strike"/"strikes", "talks"/"talk". Not a real stemmer.
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def title_tokens(title: str) -> set[str]:
    words = _WORD.findall(title.lower().replace("'s", "").replace("’s", ""))
    return {_stem(w) for w in words if w not in _STOPWORDS and len(w) > 1}


def similarity(a: set[str], b: set[str]) -> float:
    """Overlap of two headlines' content words, relative to the shorter one."""
    if not a or not b:
        return 0.0
    shared = len(a & b)
    if shared < 2:
        return 0.0
    return shared / min(len(a), len(b))
