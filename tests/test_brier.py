"""test_brier.py — Sprint 5 Phase A: Brier score pure-function tests.

Zero network calls, zero Claude calls.
"""
import pytest

from core.brier import binary_brier, multiclass_brier


def test_binary_perfect_occurred():
    assert binary_brier(1.0, True) == pytest.approx(0.0)


def test_binary_worst():
    assert binary_brier(1.0, False) == pytest.approx(1.0)


def test_binary_half():
    assert binary_brier(0.5, True) == pytest.approx(0.25)


def test_binary_tdd_spec():
    # TDD.md: my_probs {"Yes": 0.7}, outcome Yes -> brier_mine == 0.09
    assert binary_brier(0.7, True) == pytest.approx(0.09)


def test_multiclass_3outcome():
    # basket {Spain:0.30, England:0.20, Field:0.50}, Spain wins -> [1, 0, 0]
    # (1/3) * ((0.3-1)^2 + (0.2-0)^2 + (0.5-0)^2) = (1/3) * 0.78 = 0.26
    score = multiclass_brier([0.30, 0.20, 0.50], [1, 0, 0])
    assert score == pytest.approx((0.49 + 0.04 + 0.25) / 3)


def test_validation_len_mismatch():
    with pytest.raises(ValueError, match="Length mismatch"):
        multiclass_brier([0.5, 0.5], [1])


def test_validation_outcomes_not_summing_to_1():
    with pytest.raises(ValueError, match="sum"):
        multiclass_brier([0.5, 0.3, 0.2], [1, 1, 0])


def test_validation_all_zeros():
    with pytest.raises(ValueError, match="sum"):
        multiclass_brier([0.5, 0.5], [0, 0])
