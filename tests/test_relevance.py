from core.relevance import is_relevant


SYDNEY_SURF = {
    "topic_key": "WL-2",
    "topic_label": "Sydney Surf Conditions",
    "keywords": "surf;sydney;waves;swell;beach",
}
RBA = {
    "topic_key": "WL-11",
    "topic_label": "RBA, Interest Rates & Mortgages",
    "keywords": "rba;interest rates;mortgage;reserve bank;cash rate",
}
JAPAN_FOOTBALL = {
    "topic_key": "WL-5",
    "topic_label": "Japan Football / Samurai Blue",
    "keywords": "japan;samurai blue;world cup;football",
}
AI_BI = {
    "topic_key": "WL-7",
    "topic_label": "AI & Business Intelligence",
    "keywords": "ai;business intelligence;analytics;dashboard",
}
RETAIL = {
    "topic_key": "WL-10",
    "topic_label": "Retail Sales & Deals",
    "keywords": "retail;sales;discount;deals;black friday",
}


def test_sydney_surf_rejects_sweeney():
    assert is_relevant(SYDNEY_SURF, "Will Sydney Sweeney apologize for her jeans ad in 2025?") is False


def test_ai_bi_rejects_america_business_forum():
    assert is_relevant(AI_BI, "What will Trump say at the America Business Forum on November 5?") is False


def test_retail_rejects_trade_deals():
    assert is_relevant(RETAIL, "Which countries will the US agree to trade deals with before July?") is False


def test_rba_accepts_rate_market():
    assert is_relevant(RBA, "Reserve Bank of Australia decreases interest rates by 50+ bp") is True


def test_japan_football_accepts_world_cup():
    assert is_relevant(JAPAN_FOOTBALL, "World Cup: Nation To Reach Round of 16") is True


def test_surf_accepts_genuine_surf_market():
    assert is_relevant(SYDNEY_SURF, "Sydney surf swell forecast tops 3m") is True


def test_single_common_token_is_not_enough():
    assert is_relevant(JAPAN_FOOTBALL, "Will Japan raise consumption tax in 2026?") is False


def test_empty_title_is_not_relevant():
    assert is_relevant(RBA, "") is False
