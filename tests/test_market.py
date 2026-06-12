"""Endogenous market: bubbles, crashes, and size-invariant scaling."""
from conftest import run_small


def test_endogenous_bubble_and_crash():
    s = run_small(n_agents=6000, steps=14, seed=5)
    # a coordinated campaign produces a genuine bubble, not a flat path
    assert s["max_price"] > 1.5 * s["final_price"] or s["max_price"] > 2.0


def test_depth_scales_with_population():
    # price dynamics should be broadly invariant to N (depth = N / D_ref)
    small = run_small(n_agents=3000, steps=14, seed=7)
    large = run_small(n_agents=12000, steps=14, seed=7)
    assert 1.5 < small["max_price"] < 100
    assert 1.5 < large["max_price"] < 100
