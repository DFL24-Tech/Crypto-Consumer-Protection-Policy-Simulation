"""Global sensitivity analysis: the library form of the Morris/Sobol drivers."""
from dfl24sim import gsa

OUTPUTS = {"first_reduction", "fade_ratio", "sybil_coverage", "final_trust"}


def test_morris_returns_mu_star_and_sigma_per_output_and_parameter():
    res = gsa.run_morris(n_agents=300, steps=3, trajectories=2, seed=0)
    assert set(res) == OUTPUTS
    for indices in res.values():
        assert indices["names"] == gsa.PARAMETER_NAMES
        assert len(indices["mu_star"]) == len(gsa.PARAMETER_NAMES)
        assert len(indices["sigma"]) == len(gsa.PARAMETER_NAMES)
        assert all(v >= 0.0 for v in indices["mu_star"])


def test_sobol_returns_first_and_total_order_per_output_and_parameter():
    res = gsa.run_sobol(n_agents=300, steps=3, base_samples=2, seed=0)
    assert set(res) == OUTPUTS
    for indices in res.values():
        assert indices["names"] == gsa.PARAMETER_NAMES
        assert len(indices["S1"]) == len(gsa.PARAMETER_NAMES)
        assert len(indices["ST"]) == len(gsa.PARAMETER_NAMES)
