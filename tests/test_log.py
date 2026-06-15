"""test_log.py — Sprint 5 Phase A: prediction_log CRUD tests.

Zero network calls, zero Claude calls.
Uses the in-memory SQLite db fixture from conftest.py.
"""
import pytest

from core.log import list_open, record, resolve, scores


def test_record_shows_in_list_open(db):
    pid = record(db, "Will Spain win?", "Spain", 0.40, 0.35)
    assert isinstance(pid, int) and pid > 0
    rows = list_open(db)
    assert len(rows) == 1
    r = rows[0]
    assert r["question"] == "Will Spain win?"
    assert r["outcome_label"] == "Spain"
    assert r["user_prob"] == pytest.approx(0.40)
    assert r["market_prob"] == pytest.approx(0.35)
    assert r["status"] == "open"
    assert "days_open" in r
    assert r["days_open"] == 0


def test_record_market_prob_none(db):
    record(db, "AGI by 2027?", "Yes", 0.20, None)
    rows = list_open(db)
    assert rows[0]["market_prob"] is None


def test_resolve_sets_status_occurred_brier(db):
    pid = record(db, "Will Spain win?", "Spain", 0.40, 0.35)
    result = resolve(db, pid, occurred=True)
    assert result["status"] == "resolved"
    assert result["occurred"] == 1
    # binary_brier(0.40, True) = multiclass([0.40,0.60],[1,0]) = (0.36+0.36)/2 = 0.36
    assert result["brier_score"] == pytest.approx(0.36)
    assert result["resolved_at"] is not None


def test_resolve_not_occurred(db):
    pid = record(db, "AGI by 2027?", "Yes", 0.20, None)
    result = resolve(db, pid, occurred=False)
    assert result["occurred"] == 0
    # binary_brier(0.20, False) = (0.04+0.04)/2 = 0.04
    assert result["brier_score"] == pytest.approx(0.04)


def test_resolve_removes_from_list_open(db):
    pid = record(db, "Will Spain win?", "Spain", 0.40, None)
    assert len(list_open(db)) == 1
    resolve(db, pid, occurred=True)
    assert list_open(db) == []


def test_double_resolve_refused(db):
    pid = record(db, "Will Spain win?", "Spain", 0.40, None)
    resolve(db, pid, occurred=True)
    with pytest.raises(ValueError, match="already resolved"):
        resolve(db, pid, occurred=False)


def test_resolve_unknown_id_refused(db):
    with pytest.raises(ValueError, match="not found"):
        resolve(db, 9999, occurred=True)


def test_scores_rows_and_means(db):
    # pid1: user=0.40, market=0.35, occurred=True
    #   user_brier  = binary_brier(0.40, True)  = 0.36
    #   market_brier = binary_brier(0.35, True) = (0.35-1)^2 = 0.4225
    pid1 = record(db, "Will Spain win?", "Spain", 0.40, 0.35)
    # pid2: user=0.20, market=None, occurred=False
    #   user_brier  = binary_brier(0.20, False) = 0.04
    pid2 = record(db, "AGI by 2027?", "Yes", 0.20, None)
    resolve(db, pid1, occurred=True)
    resolve(db, pid2, occurred=False)

    result = scores(db)
    rows = result["rows"]
    assert len(rows) == 2

    assert result["mean_user_brier"] == pytest.approx((0.36 + 0.04) / 2)  # 0.20
    # market mean from pid1 only: binary_brier(0.35, True) = 0.4225
    assert result["mean_market_brier"] == pytest.approx((0.35 - 1.0) ** 2)  # 0.4225

    row1 = next(r for r in rows if r["question"] == "Will Spain win?")
    row2 = next(r for r in rows if r["question"] == "AGI by 2027?")
    assert row1["market_brier"] == pytest.approx(0.4225)
    assert row2["market_brier"] is None


def test_scores_no_market_mean_when_absent(db):
    pid = record(db, "Test?", "Yes", 0.60, None)
    resolve(db, pid, occurred=True)
    result = scores(db)
    assert result["mean_market_brier"] is None


def test_scores_empty_when_no_resolved(db):
    record(db, "Open question?", "Yes", 0.50, None)
    result = scores(db)
    assert result["rows"] == []
    assert result["mean_user_brier"] is None
    assert result["mean_market_brier"] is None
