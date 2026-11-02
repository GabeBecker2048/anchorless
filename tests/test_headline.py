"""The consensus headline: chosen from what outlets wrote, never from who they are."""

import random

from anchorless import headline
from anchorless.models import Cluster, Story


def story(outlet, title, summary="A summary.", key=None):
    return Story(key=key or f"{outlet}|{title}", title=title, summary=summary, outlet=outlet, url="",
                 published=None, scope="national", category="general")


def cluster(*stories):
    return Cluster(stories=list(stories))


SUMMARIES = {
    "senate": "The Senate passed the bill 52-48 on Tuesday, sending the spending measure to the president.",
}


def plane(lead):
    """A plain story four outlets carry; ``lead`` is shown by default."""
    s = "A Learjet carrying nine people crashed in Florida on Monday, killing everyone on board, officials said."
    return cluster(lead,
                   story("B", "Learjet with nine aboard crashes in Florida, killing all", s),
                   story("C", "Nine killed as Learjet crashes in Florida", s),
                   story("D", "Florida Learjet crash kills nine people on board", s))


def test_a_plain_default_is_never_replaced():
    c = plane(story("A", "Nine dead after Learjet crashes near Florida airport",
                    "Nine people died when a Learjet crashed in Florida, officials said."))
    choice = headline.choose(c, 0.15)
    assert not choice.changed and "no red flag" in choice.reason


def test_a_spun_default_is_replaced_by_the_consensus():
    c = plane(story("A", "Biden's FAA under fire as Learjet SLAMS into Florida in shocking crash",
                    "Nine people died in a Learjet crash in Florida."))
    choice = headline.choose(c, 0.15)
    assert choice.changed and choice.chosen.outlet != "A"
    a = next(x for x in choice.scores if x.story.outlet == "A")
    assert any("loaded" in p for p in a.penalties)


def test_a_loaded_word_everyone_uses_is_not_spin():
    s = "A Category 4 hurricane made landfall in Florida on Tuesday."
    c = cluster(story("A", "Hurricane slams Florida coast as Category 4 storm", s),
                story("B", "Category 4 hurricane slams into Florida coast", s),
                story("C", "Hurricane slams Florida, making landfall as Category 4", s))
    for x in headline.score_versions(c):
        assert not x.penalties, x


def test_acronyms_reported_quotes_and_names_are_not_penalised():
    s = "Officials said on Monday."
    for title in ('Trump tells GOP "we gave this a very strong shot"',
                  "Michael Wilbon announces indefinite leave from ESPN, 'PTI'",
                  "FBI and NTSB investigate NASA contractor plane crash",
                  "I'm Dr Abdul El-Sayed. This is why I want Michigan's vote"):
        c = cluster(story("A", title, s), story("B", title.lower(), s))
        x = next(x for x in headline.score_versions(c) if x.story.outlet == "A")
        assert not x.penalties, (title, x.penalties)


def test_shouting_and_exclamations_are_penalised_when_others_dont():
    s = "The bill passed."
    c = cluster(story("A", "Senate PASSES spending bill!", s), story("B", "Senate passes spending bill", s))
    x = next(x for x in headline.score_versions(c) if x.story.outlet == "A")
    assert "exclamation" in x.penalties and "all caps" in x.penalties


def test_one_outlet_is_left_alone():
    c = cluster(story("A", "Senate SLAMS everyone in shocking vote"), story("A", "Another version, same outlet"))
    assert headline.choose(c, 0.15) is None


def test_versions_that_dont_agree_are_left_alone():
    c = cluster(story("A", "Senate passes spending bill", "Vote 52-48."),
                story("B", "Lions linebacker taken to hospital after tackle", "He was moving."),
                story("C", "Bitcoin falls below record as markets wobble", "Prices fell."))
    choice = headline.choose(c, 0.15)
    assert not choice.changed and "don't agree" in choice.reason


def test_a_question_is_never_swapped_in_for_a_statement():
    s = "The senate race in Ohio is close, polls show, as Husted and Brown campaign."
    c = cluster(story("A", "Husted SLAMS Brown in Ohio senate race", s),
                story("B", "Who will win the Ohio senate race between Husted and Brown?", s),
                story("C", "Husted and Brown campaign in close Ohio senate race", s))
    choice = headline.choose(c, 0.15)
    assert not choice.chosen.title.endswith("?")


def test_the_choice_does_not_depend_on_who_the_outlets_are():
    rng = random.Random(3)
    titles = ["Biden's FAA under fire as Learjet SLAMS into Florida in shocking crash",
              "Learjet with nine aboard crashes in Florida, killing all",
              "Nine killed as Learjet crashes in Florida",
              "Florida Learjet crash kills nine people on board"]
    s = "A Learjet carrying nine people crashed in Florida, killing everyone, officials said."
    picked = set()
    for _ in range(12):
        names = rng.sample(["Fox News", "CNN", "BBC News", "NPR", "PBS NewsHour", "The Guardian"], 4)
        c = cluster(*[story(n, t, s) for n, t in zip(names, titles, strict=True)])
        choice = headline.choose(c, 0.15)
        picked.add(choice.chosen.title)
    assert len(picked) == 1 and "SLAMS" not in picked.pop()


def test_a_chosen_headline_sticks():
    c = plane(story("A", "Biden's FAA under fire as Learjet SLAMS into Florida in shocking crash",
                    "Nine people died in a Learjet crash in Florida."))
    first = headline.choose(c, 0.15)
    again = headline.choose(c, 0.15, previous_key=first.chosen.key)
    assert again.chosen is first.chosen
