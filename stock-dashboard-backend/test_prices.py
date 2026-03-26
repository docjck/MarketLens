import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from main import _compute_pct_change


def test_normal_gain():
    assert _compute_pct_change(105.0, 100.0) == 5.0


def test_normal_loss():
    assert _compute_pct_change(95.0, 100.0) == -5.0


def test_last_price_none():
    assert _compute_pct_change(None, 100.0) is None


def test_prev_close_none():
    assert _compute_pct_change(105.0, None) is None


def test_both_none():
    assert _compute_pct_change(None, None) is None


def test_prev_close_zero():
    assert _compute_pct_change(105.0, 0) is None


def test_result_rounded_to_two_decimals():
    result = _compute_pct_change(101.005, 100.0)
    assert result == round((101.005 - 100.0) / 100.0 * 100, 2)
