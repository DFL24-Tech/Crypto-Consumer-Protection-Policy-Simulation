"""One-at-a-time robustness sweeps: the library form of sweep.py."""
import pytest

from dfl24sim import sweeps

NAMES = {
    "friction_efficacy", "habituation_fade", "adaptive_coverage",
    "overfriction_trust", "grooming_victim_reduction", "margin_systemic",
}


def test_registry_names_the_six_paper_sweeps_with_vocabulary():
    assert set(sweeps.SWEEPS) == NAMES
    for meta in sweeps.SWEEPS.values():
        assert meta["parameter"]["symbol"]
        assert meta["parameter"]["meaning"]
        assert meta["grid"]
        assert meta["outcomes"]
        for meaning in meta["outcomes"].values():
            assert meaning


def test_friction_efficacy_returns_one_point_per_grid_value():
    res = sweeps.run_sweep("friction_efficacy", n_agents=300, steps=3, seeds=(0,))
    grid = sweeps.SWEEPS["friction_efficacy"]["grid"]
    assert res["sweep"] == "friction_efficacy"
    assert res["parameter"]["symbol"] == "phi"
    assert [p["value"] for p in res["points"]] == list(grid)
    for point in res["points"]:
        assert isinstance(point["first_reduction"], float)


def test_adaptive_coverage_carries_the_static_reference():
    res = sweeps.run_sweep("adaptive_coverage", n_agents=300, steps=3, seeds=(0,))
    assert 0.0 <= res["reference"]["static_detection"] <= 1.0
    for point in res["points"]:
        assert 0.0 <= point["sybil_detection"] <= 1.0


def test_margin_systemic_reports_both_outcomes_per_point():
    res = sweeps.run_sweep("margin_systemic", n_agents=300, steps=3, seeds=(0,))
    for point in res["points"]:
        assert isinstance(point["liquidated_frac"], float)
        assert isinstance(point["trough_drawdown"], float)


@pytest.mark.parametrize("name", sorted(sweeps.SWEEPS))
def test_every_registered_sweep_runs_and_reports_its_outcomes(name):
    """Each runner's scenario and metric keys must exist, not just compile."""
    res = sweeps.run_sweep(name, n_agents=300, steps=3, seeds=(0,))
    assert [p["value"] for p in res["points"]] == list(sweeps.SWEEPS[name]["grid"])
    for point in res["points"]:
        for outcome in sweeps.SWEEPS[name]["outcomes"]:
            assert outcome in point


def test_unknown_sweep_name_is_rejected():
    with pytest.raises(ValueError, match="friction_efficacy"):
        sweeps.run_sweep("vibes", n_agents=300, steps=3, seeds=(0,))
