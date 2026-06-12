"""Behavioural kernel: dual-process decisions and point-of-action friction."""
from conftest import run_small


def test_runs_and_reports_valid_precision():
    s = run_small(n_agents=2000, steps=8)
    assert s["n_agents"] == 2000
    assert 0.0 <= s["friction_precision"] <= 1.0


def test_friction_fires_only_on_high_risk():
    # With no false-positive rate, every fired prompt must land on a high-risk action.
    s = run_small(n_agents=5000, steps=14, seed=1)
    assert s["friction_precision"] == 1.0
    assert s["friction_on_safe"] == 0
