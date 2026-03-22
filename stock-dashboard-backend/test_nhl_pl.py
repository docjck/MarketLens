# test_nhl_pl.py
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from nhl_router import ml_to_units

def test_favorite_win():
    result = ml_to_units(-140, "WIN")
    assert abs(result - round(100 / 140, 4)) < 0.0001

def test_underdog_win():
    result = ml_to_units(120, "WIN")
    assert abs(result - round(120 / 100, 4)) < 0.0001

def test_loss():
    assert ml_to_units(-140, "LOSS") == -1.0
    assert ml_to_units(120,  "LOSS") == -1.0

def test_pending():
    assert ml_to_units(-140, "PENDING") is None
    assert ml_to_units(None, "WIN")    is None

def test_fallback_model_prob():
    result = ml_to_units(None, "WIN", model_prob=0.60)
    assert abs(result - round(0.40 / 0.60, 4)) < 0.0001

def test_fallback_loss():
    result = ml_to_units(None, "LOSS", model_prob=0.60)
    assert result == -1.0

def test_invalid_ml_zero():
    assert ml_to_units(0, "WIN") is None

def test_unknown_result():
    assert ml_to_units(-140, "UNKNOWN") is None
    assert ml_to_units(-140, "") is None

def test_model_prob_clamped_high():
    # model_prob=0.90 exceeds 0.80 ceiling; should clamp to 0.80
    result = ml_to_units(None, "WIN", model_prob=0.90)
    assert abs(result - round(0.20 / 0.80, 4)) < 0.0001

def test_model_prob_clamped_low():
    # model_prob=0.10 is below 0.20 floor; should clamp to 0.20
    result = ml_to_units(None, "WIN", model_prob=0.10)
    assert abs(result - round(0.80 / 0.20, 4)) < 0.0001
