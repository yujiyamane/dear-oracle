"""tests/test_market_history.py — prob history carried forward inside do_hits.json."""
import json

from core.market_history import attach_history, load_prev_history


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_load_prev_missing_file(tmp_path):
    assert load_prev_history(tmp_path / "nope.json") == ({}, "")


def test_load_prev_corrupt_file(tmp_path):
    p = tmp_path / "do_hits.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_prev_history(p) == ({}, "")


def test_load_prev_collects_hits_and_pool(tmp_path):
    p = tmp_path / "do_hits.json"
    _write(p, {
        "meta": {"date_syd": "2026-07-03"},
        "hits": {"WL-5": [{"url": "https://pm.com/a", "prob_now": 0.5, "history": [0.4, 0.5]}]},
        "pool": [{"url": "https://pm.com/b", "prob_now": 0.7}],
    })
    prev, prev_date = load_prev_history(p)
    assert prev_date == "2026-07-03"
    assert prev["https://pm.com/a"] == [0.4, 0.5]
    assert prev["https://pm.com/b"] == [0.7]


def test_attach_appends_on_new_day():
    items = [{"url": "https://pm.com/a", "prob_now": 0.6}]
    attach_history(items, {"https://pm.com/a": [0.4, 0.5]}, "2026-07-04", "2026-07-03")
    assert items[0]["history"] == [0.4, 0.5, 0.6]


def test_attach_replaces_last_on_same_day_rerun():
    items = [{"url": "https://pm.com/a", "prob_now": 0.65}]
    attach_history(items, {"https://pm.com/a": [0.4, 0.5]}, "2026-07-04", "2026-07-04")
    assert items[0]["history"] == [0.4, 0.65]


def test_attach_caps_at_seven():
    items = [{"url": "https://pm.com/a", "prob_now": 0.9}]
    attach_history(items, {"https://pm.com/a": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]}, "2026-07-04", "2026-07-03")
    assert items[0]["history"] == [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.9]


def test_attach_unknown_url_starts_fresh():
    items = [{"url": "https://pm.com/new", "prob_now": 0.3}]
    attach_history(items, {}, "2026-07-04", "2026-07-03")
    assert items[0]["history"] == [0.3]


def test_attach_skips_items_without_url_or_prob():
    items = [{"prob_now": 0.3}, {"url": "https://pm.com/x"}]
    attach_history(items, {}, "2026-07-04", "2026-07-03")
    assert "history" not in items[0]
    assert "history" not in items[1]


def test_scan_carries_history_forward(tmp_path):
    from core import scan as scan_mod

    out = tmp_path / "do_hits.json"
    _write(out, {
        "meta": {"date_syd": "2026-07-03", "status": "ok"},
        "hits": {},
        "pool": [{"url": "https://polymarket.com/event/rba-august/m1", "prob_now": 0.85, "history": [0.85]}],
    })

    class _M:
        url = "https://polymarket.com/event/rba-august/m1"
        prob_now = 0.88
        prob_7d_ago = 0.87
        outcome_label = "No change"

    class _E:
        event_title = "Reserve Bank of Australia Decision in August"
        volume_usd = 50_000.0
        markets = [_M()]

    class _Adapter:
        def top_by_volume(self, limit=50):
            return [_E()]

        def public_search(self, q, limit=5):
            return [_E()]

    result = scan_mod.scan(watchlist=[], adapter=_Adapter(), out_path=out)
    pool = result["pool"]
    assert pool and pool[0]["history"][-1] == 0.88
    assert pool[0]["history"][0] == 0.85
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["pool"][0]["history"] == pool[0]["history"]
