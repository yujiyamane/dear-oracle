"""tests/test_market_notes.py"""
from core.market_notes import annotate_pool, build_note, classify_relevance


def test_classify_rba():
    assert classify_relevance("Reserve Bank of Australia Decision in August") == "rba"
    assert classify_relevance("RBA cash rate August") == "rba"


def test_classify_ai_word_boundary():
    assert classify_relevance("OpenAI releases new model") == "ai"
    assert classify_relevance("Will AI pass the bar exam") == "ai"
    assert classify_relevance("Ukraine ceasefire by September") == "none"


def test_classify_property_and_politics():
    assert classify_relevance("Sydney house prices to fall 10%") == "property"
    assert classify_relevance("Australian federal election winner") == "au_politics"


def test_classify_none():
    assert classify_relevance("World Cup Winner") == "none"


def test_build_note_bands():
    base = {"outcome_label": "France", "relevance": "none"}
    assert "steady" in build_note({**base, "delta_7d": None})
    assert "steady" in build_note({**base, "delta_7d": 0.004})
    assert "firmed" in build_note({**base, "delta_7d": 0.02})
    assert "slipped" in build_note({**base, "delta_7d": -0.02})
    assert "jumped" in build_note({**base, "delta_7d": 0.09})
    assert "surged" in build_note({**base, "delta_7d": 0.47})
    assert "collapsed" in build_note({**base, "delta_7d": -0.20})


def test_build_note_mentions_pp_and_implication():
    note = build_note({"outcome_label": "No change", "relevance": "rba", "delta_7d": 0.01})
    assert "+1pp" in note
    assert "mortgage" in note


def test_annotate_pool_adds_fields_and_sorts():
    pool = [
        {"title": "World Cup Winner", "outcome_label": "France", "delta_7d": 0.14},
        {"title": "RBA Decision in August", "outcome_label": "No change", "delta_7d": 0.01},
    ]
    out = annotate_pool(pool)
    assert out[0]["relevance"] == "rba"
    assert out[1]["relevance"] == "none"
    assert all("note" in m and "relevance" in m for m in out)
    assert pool[0].get("note") is None
