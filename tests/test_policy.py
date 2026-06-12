"""Compliance policy: the coverage gap and its collapse under adaptation."""
from conftest import run_small, detection


def test_coverage_gap_ordering():
    det = detection(run_small(n_agents=8000, steps=14, seed=2, adaptive_adversary=False))
    assert det["sybil_attacker"] > 0.95        # fully covered
    assert det["cyber_red_team"] < 0.05         # uncovered by construction
    assert det["cyber_red_team"] < det["sybil_attacker"]


def test_adaptation_collapses_detection():
    static = detection(run_small(n_agents=8000, steps=14, seed=3, adaptive_adversary=False))
    adapt = detection(run_small(n_agents=8000, steps=14, seed=3, adaptive_adversary=True))
    assert adapt["sybil_attacker"] < static["sybil_attacker"]
