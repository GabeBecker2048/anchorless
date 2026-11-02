"""Which outlet's headline to show for a story several outlets carry.

The "consensus" headline: the version whose words the *other* outlets corroborate.
Spin - "slams", "meltdown", a loaded label - is usually one outlet's own wording,
while the facts (names, places, numbers, what happened) appear across outlets. No
outlet is named or rated anywhere here: the choice comes only from what the outlets
wrote.

Built to avoid false positives - passing over a plain, legitimate headline:
- a word counts as corroborated if another outlet has it in its headline *or summary*,
  so a legitimate specific only one headline carries still counts;
- style penalties are small and apply only to wording no other outlet's headline uses
  ("Hurricane slams coast" from four outlets is consensus, not spin);
- the default (the first-published version) is only replaced when another version is
  better by a clear margin, doubled when only two outlets carry the story;
- a chosen headline sticks across refreshes unless beaten by that margin again.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from .models import Cluster, Story
from .text import title_tokens

CORROBORATION_WEIGHT, COVERAGE_WEIGHT = 0.7, 0.3

# Editorializing words, as they appear in headlines. Deliberately short: a word goes
# here only if it is almost always opinion when one outlet uses it and the others don't.
# Words with common literal meanings in news are left out on purpose: erupts (volcanoes),
# explosive / blasts / blasted (explosions), destroys (fires), brutal (heat), fumes (gas).
LOADED_WORDS = frozenset("""
slams slammed slamming rips ripped torches torched eviscerates eviscerated
obliterates obliterated shreds shredded skewers skewered mocks mocked owns owned
meltdown unhinged bombshell shocking stunning humiliating humiliation disgraceful disgusting
insane outrageous laughable pathetic epic jaw-dropping scathing
lashes furious seethes
""".split())
PENALTY_LOADED, PENALTY_LOADED_CAP = 0.06, 0.15
PENALTY_CAPS, PENALTY_EXCLAIM, PENALTY_QUESTION = 0.05, 0.05, 0.03

# All-caps words that are names, not shouting.
ACRONYMS = frozenset("""
US USA UK EU UN NATO FBI CIA NSA DOJ DHS ICE IRS FAA FDA CDC NIH NASA NFL NBA NHL MLB NCAA
GOP DNC RNC AI COVID WHO IMF OPEC LGBTQ CEO CFO GDP CPI SEC FTC FCC EPA ATF DEA TSA HIV
AIDS NYPD LAPD SWAT ISIS BBC CNN NPR PBS ABC CBS NBC CNBC MSNBC UFC UAW AFL CIO NAACP ACLU
ESPN PTI NASCAR FIFA UEFA OSHA FEMA NOAA HUD USDA NTSB NHTSA PGA LPGA WNBA MLS NATO
""".split())

_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
# Quoted speech: what someone *said*, not the outlet's own words. Double quotes, or single
# quotes that open at the start of a word (so the apostrophe in "Michigan's" isn't one).
_QUOTES = re.compile(r"[\"“”][^\"“”]*[\"“”]"
                     r"|(?<![\w’'])['‘](?:[^'‘’]|(?<=\w)['’](?=\w))+['’](?!\w)")   # apostrophes inside allowed


def outside_quotes(text: str) -> str:
    """The headline without its quoted passages."""
    return _QUOTES.sub(" ", text or "")


@dataclass
class Scored:
    story: Story
    total: float
    corroboration: float
    coverage: float
    penalties: list[str] = field(default_factory=list)

    def why(self) -> str:
        bits = [f"corroborated {self.corroboration:.2f}", f"coverage {self.coverage:.2f}"]
        return ", ".join(bits + self.penalties)


def _words(text: str) -> list[str]:
    return _WORD.findall(text or "")


def _penalties(s: Story, others: list[Story], all_others_question: bool) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    title = s.title
    own = outside_quotes(title)           # loaded words and "!" only count in the outlet's own words
    other_headline_words = {w.lower() for o in others for w in _words(o.title)}
    loaded = [w for w in {w.lower() for w in _words(own)} if w in LOADED_WORDS and w not in other_headline_words]
    if loaded:
        out.append((f"loaded: {', '.join(sorted(loaded))}", min(PENALTY_LOADED * len(loaded), PENALTY_LOADED_CAP)))
    # Shouting, not acronyms: an all-caps word of 6+ letters, or two of 5+ in a row.
    words = [w.strip("'’-") for w in _words(title)]
    shout = [w.isupper() and len(w) >= 5 and w not in ACRONYMS for w in words]
    if any(s and len(w) >= 6 for s, w in zip(shout, words, strict=True)) or any(
            a and b for a, b in zip(shout, shout[1:], strict=False)):
        out.append(("all caps", PENALTY_CAPS))
    if "!" in own:
        out.append(("exclamation", PENALTY_EXCLAIM))
    if title.rstrip().endswith("?") and not all_others_question:
        out.append(("question", PENALTY_QUESTION))
    return out


def score_versions(cluster: Cluster) -> list[Scored]:
    """Every version of a story, scored. Higher is more corroborated, more complete, plainer.

    Every content word counts the same. (Weighting rare words up was tried: a legitimate
    detail only one outlet mentions - "near the airport" - is rare *and* unshared, so it
    sank good headlines. Corroboration can't tell an unshared fact from unshared spin.)"""
    outlets = {s.outlet for s in cluster.stories}
    # What each outlet said, headlines and summaries together, for corroboration.
    said: dict[str, set[str]] = {o: set() for o in outlets}
    heads: dict[str, set[str]] = {o: set() for o in outlets}
    for s in cluster.stories:
        said[s.outlet] |= title_tokens(s.title) | title_tokens(s.summary)
        heads[s.outlet] |= title_tokens(s.title)
    # The story's core facts: headline words at least half the outlets use (and 2+).
    need = max(2, math.ceil(len(outlets) / 2))
    counts = Counter(t for o in outlets for t in heads[o])
    core = {t for t, k in counts.items() if k >= need}
    out = []
    for s in cluster.stories:
        others = [o for o in outlets if o != s.outlet]
        toks = title_tokens(s.title)
        if not toks or not others:
            out.append(Scored(s, 0.0, 0.0, 0.0))
            continue
        corroboration = sum(sum(1 for o in others if t in said[o]) / len(others) for t in toks) / len(toks)
        coverage = len(toks & core) / len(core) if core else 1.0
        other_stories = [o for o in cluster.stories if o.outlet != s.outlet]
        pen = _penalties(s, other_stories, all(o.title.rstrip().endswith("?") for o in other_stories))
        total = CORROBORATION_WEIGHT * corroboration + COVERAGE_WEIGHT * coverage - sum(p for _, p in pen)
        out.append(Scored(s, total, corroboration, coverage, [name for name, _ in pen]))
    return out


@dataclass
class Choice:
    chosen: Story
    default: Story
    scores: list[Scored]
    reason: str

    @property
    def changed(self) -> bool:
        return self.chosen is not self.default


# The story's versions must agree for there to be a consensus (median corroboration).
COHERENT_MEDIAN = 0.4
# "Odd one out" - a last resort, since unshared words may be legitimate detail: under
# this much of the headline is shared, *and* it trails the other versions by this much.
ODD_ONE_OUT_BELOW, ODD_ONE_OUT_GAP = 0.35, 0.35


def choose(cluster: Cluster, margin: float, previous_key: str | None = None) -> Choice | None:
    """The headline to show, or None when there is nothing to choose (one outlet).

    ``cluster.stories[0]`` is the default (first published, with a summary). It is only
    replaced when it has a red flag - a style penalty, or wording the other outlets
    clearly don't share - and a clean, at-least-as-complete version beats it by
    ``margin`` (twice that with two outlets). ``previous_key`` is the version shown last
    refresh: it stays unless the same test says otherwise.
    """
    outlets = {s.outlet for s in cluster.stories}
    if len(outlets) < 2:
        return None
    scores = score_versions(cluster)
    by_story = {id(x.story): x for x in scores}
    default = cluster.stories[0]
    incumbent = next((x for x in scores if x.story.key == previous_key), None) or by_story[id(default)]
    which = "previous" if incumbent.story.key == previous_key else "default"
    corr = sorted(x.corroboration for x in scores)
    median = corr[len(corr) // 2]
    if median < COHERENT_MEDIAN:
        return Choice(incumbent.story, default, scores, "kept: the versions don't agree enough to call a consensus")
    others = [x.corroboration for x in scores if x.story.outlet != incumbent.story.outlet] or [0.0]
    odd = (incumbent.corroboration < ODD_ONE_OUT_BELOW
           and incumbent.corroboration < sorted(others)[len(others) // 2] - ODD_ONE_OUT_GAP)
    if not incumbent.penalties and not odd:
        return Choice(incumbent.story, default, scores, f"kept: the {which} has no red flag")
    m = margin * (2 if len(outlets) == 2 else 1)
    asks = incumbent.story.title.rstrip().endswith("?")
    pool = [x for x in scores
            if x is not incumbent and not x.penalties
            and (x.story.summary or not incumbent.story.summary)        # a summary beats none
            and (asks or not x.story.title.rstrip().endswith("?"))      # no swapping in a question
            and x.coverage >= incumbent.coverage - 0.1                   # not less complete
            and x.total >= incumbent.total + m]
    if not pool:
        return Choice(incumbent.story, default, scores, f"kept: no clean version clearly better than the {which}")
    best = max(pool, key=lambda x: x.total)
    flag = ", ".join(incumbent.penalties) if incumbent.penalties else "its wording is the odd one out"
    reason = (f"the {which} has a red flag ({flag}); this one is {best.total - incumbent.total:+.2f} "
              f"({best.why()} vs {incumbent.why()})")
    return Choice(best.story, default, scores, reason)


def apply(cluster: Cluster, story: Story) -> None:
    """Show ``story``: it becomes the lead; the rest keep their order."""
    cluster.stories.remove(story)
    cluster.stories.insert(0, story)
