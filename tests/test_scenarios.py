"""Scenario engine, the twelve scenarios, and the new mechanisms."""
from dfl24sim import scenarios as sc


def test_twelve_scenarios_build_and_run():
    assert len(sc.SCENARIOS) == 12
    for name in sc.SCENARIOS:
        agg, _ = sc.run_scenario(name, n_agents=2000, steps=8, seeds=(0,))
        assert "coverage" in agg and 0.0 <= agg["coverage"] <= 1.0


def test_liquidation_cascade_fires():
    agg, _ = sc.run_scenario("A3_crash_cascade", n_agents=4000, steps=14, seeds=(0, 1))
    assert agg["liquidated_frac"] > 0.0


def test_alert_fatigue_erodes_trust():
    base, _ = sc.run_scenario("A1_calm_baseline", n_agents=4000, steps=14, seeds=(0, 1))
    fatigue, _ = sc.run_scenario("D2_over_friction_fatigue", n_agents=4000, steps=14, seeds=(0, 1))
    assert fatigue["false_positives"] > 0
    assert fatigue["final_trust"] < base["final_trust"]
    assert fatigue["precision"] < 1.0


def test_grooming_blunts_friction():
    agg, _ = sc.run_scenario("C1_pig_butchering_wave", n_agents=5000, steps=14, seeds=(0, 1))
    assert agg["scam_victim_frac"] > 0.0
    red = (agg["victim_take_control"] - agg["victim_take_friction"]) / agg["victim_take_control"]
    assert red < 0.25                          # friction is far weaker on groomed victims


def test_battery_matrix_shape():
    bat = sc.run_battery(n_agents=2000, steps=8, seeds=(0,))
    assert len(bat) == len(sc.POLICY_REGIMES) * len(sc.ATTACK_WORLDS)
    assert {"policy", "attack", "coverage", "final_trust"}.issubset(bat.columns)


def test_battery_figure_renders_coverage_and_trust_heatmaps():
    import io

    bat = sc.run_battery(n_agents=300, steps=3, seeds=(0,))
    fig = sc.battery_figure(bat)
    try:
        titles = " ".join(ax.get_title().lower() for ax in fig.axes)
        assert "detection" in titles
        assert "trust" in titles
        buf = io.BytesIO()
        fig.savefig(buf, format="png")
        assert buf.getvalue().startswith(b"\x89PNG\r\n\x1a\n")
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)
