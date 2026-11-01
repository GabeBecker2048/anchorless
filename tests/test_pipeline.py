from anchorless.breaking import pick_breaking
from anchorless.config import SegmentConfig
from anchorless.pipeline import all_clusters, build_rundown
from anchorless.store import Store

from .conftest import NOW


def test_parse_skips_filler_and_cleans(stories):
    titles = [s.title for s in stories]
    assert "Here's the latest." not in titles
    assert "River flooding forces evacuations in Riverton" in titles
    flood = next(s for s in stories if s.title.startswith("River flooding"))
    assert flood.summary.startswith("Thousands of residents")
    assert flood.raw_title.startswith("Live updates:")


def test_same_story_from_two_outlets_is_one_cluster(stories, cfg):
    clusters = all_clusters(stories, cfg, NOW)
    flood = [c for c in clusters if "Riverton" in c.lead.title]
    assert len(flood) == 1
    assert flood[0].outlets == ["Outlet A", "Outlet B"] or set(flood[0].outlets) == {"Outlet A", "Outlet B"}
    # Covered by two outlets, it ranks first.
    assert clusters[0] is flood[0]


def test_old_stories_age_out(stories, cfg):
    clusters = all_clusters(stories, cfg, NOW)
    assert not any("shipwreck" in c.lead.title for c in clusters)


def test_segments_never_repeat_a_story(stories, cfg):
    cfg.rundown.segment = [SegmentConfig(name="TOP", stories=2), SegmentConfig(name="ALL", stories=10)]
    rundown = build_rundown(all_clusters(stories, cfg, NOW), cfg, NOW)
    keys = [c.key for c in rundown.clusters]
    assert len(keys) == len(set(keys))
    assert rundown.segments[0].name == "TOP" and len(rundown.segments[0].clusters) == 2


def test_category_segment(stories, cfg):
    cfg.source[1].category = "business"
    for s in stories:
        if s.outlet == "Outlet B":
            s.category = "business"
    cfg.rundown.segment = [SegmentConfig(name="BUSINESS", stories=3, category="business")]
    rundown = build_rundown(all_clusters(stories, cfg, NOW), cfg, NOW)
    assert all(any(s.category == "business" for s in c.stories) for c in rundown.clusters)


def test_breaking_prefix_alerts_once(stories, cfg):
    store = Store(":memory:")
    store.mark_seen(stories, NOW)
    clusters = all_clusters(stories, cfg, NOW)
    hit = pick_breaking(clusters, cfg.breaking, store, NOW)
    assert hit is not None and "Volcano" in hit.lead.title
    # Never the same story twice, even after the cooldown.
    later = NOW.replace(hour=NOW.hour + 1)
    assert pick_breaking(clusters, cfg.breaking, store, later) is None


def test_breaking_needs_enough_outlets(stories, cfg):
    cfg.breaking.title_prefixes = []
    store = Store(":memory:")
    store.mark_seen(stories, NOW)
    assert pick_breaking(all_clusters(stories, cfg, NOW), cfg.breaking, store, NOW) is None
    cfg.breaking.min_sources = 2
    cfg.breaking.window_minutes = 120
    hit = pick_breaking(all_clusters(stories, cfg, NOW), cfg.breaking, store, NOW)
    assert hit is not None and "Riverton" in hit.lead.title


def test_store_keeps_first_seen(stories, tmp_path):
    store = Store(tmp_path / "s.sqlite3")
    store.mark_seen(stories, NOW)
    store.close()
    store = Store(tmp_path / "s.sqlite3")
    later = NOW.replace(hour=18)
    store.mark_seen(stories, later)
    assert all(s.first_seen == NOW for s in stories)
