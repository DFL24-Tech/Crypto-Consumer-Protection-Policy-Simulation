"""The precomputed reference bundle: the paper's headline numbers with provenance.

The numbers live in reference_data.json, extracted from the repository's
results/ artifacts by server/scripts/build_reference_data.py and shipped as
package data — so the tool answers instantly, with no database, queue, or
simulation run. This module owns the curation: per-topic headlines, the
white-paper section each number comes from, and the caveat that every figure
is a simulation result rather than a field measurement.
"""
import json
from importlib import resources

CAVEAT = (
    "These are simulation results from the DFL24-Sim agent-based model, not "
    "field measurements. The platform exists to make a subsequent field "
    "experiment cheaper and pre-registered, not to replace it."
)

TOPICS = {
    "calibration": {
        "headline": (
            "SMM calibration converged: friction's first-exposure reduction "
            "lands at ~14.3% against the field-anchored 9.5% target "
            "(Havakhor et al.'s 8.6-10.5% effect)."
        ),
        "whitepaper_section": (
            "White paper §6.3 (the calibrated friction effect); "
            "calibration method in MODEL.md §7"
        ),
        "source_files": ["results/calibration.json"],
    },
    "sensitivity": {
        "headline": (
            "Each headline output is driven by one mechanism with no "
            "cross-leakage: efficacy <- phi (Sobol S1 ~0.85), sybil coverage "
            "<- epsilon (S1 ~0.96), trust <- theta_fa (S1 ~0.93), and fade "
            "<- eta (dominant by Morris mu* and total-order ST)."
        ),
        "whitepaper_section": (
            "White paper, global sensitivity analysis section "
            "(Morris screening + Sobol indices)"
        ),
        "source_files": [
            "results/gsa/morris.json",
            "results/gsa/sobol.json",
            "results/sensitivity/sweeps.json",
        ],
    },
    "coverage": {
        "headline": (
            "Rule-based surveillance catches 50-100% of scripted adversaries "
            "but collapses to ~9-19% once they adapt; the cyber class is "
            "never caught."
        ),
        "whitepaper_section": (
            "White paper §6.2 (the coverage map of rule-based surveillance)"
        ),
        "source_files": ["results/coverage.csv", "results/coverage_adaptive.csv"],
    },
    "fade": {
        "headline": (
            "The ~14% first-exposure friction effect erodes to ~9% by day 14 "
            "as users habituate (fade ratio ~0.56); the fade is emergent and "
            "vanishes when habituation is switched off."
        ),
        "whitepaper_section": (
            "White paper §6.3 (friction's fading first-exposure effect)"
        ),
        "source_files": ["results/fade.csv", "results/calibration.json"],
    },
    "battery": {
        "headline": (
            "Across 4 policy regimes x 5 attack worlds, over-friction matches "
            "standard on coverage but destroys trust in every attack world — "
            "a dominated policy. Deploy standard or tiered, never "
            "over-friction."
        ),
        "whitepaper_section": (
            "White paper §6.6 (policy recommendation from the "
            "policy x attack battery)"
        ),
        "source_files": ["results/scenarios/battery.csv"],
    },
    "validation": {
        "headline": (
            "The market reproduces stylized facts it was never fitted to — "
            "fat tails (excess kurtosis ~47) and volatility clustering — and "
            "the headline metrics are Monte-Carlo converged across 16 seeds."
        ),
        "whitepaper_section": (
            "White paper, pattern-oriented validation section "
            "(stylized facts, convergence, adversary floor)"
        ),
        "source_files": ["results/gsa/validation.json"],
    },
}

_DATA = json.loads(
    resources.files("dfl24sim_server")
    .joinpath("reference_data.json")
    .read_text(encoding="utf-8")
)


def describe(topic: str) -> dict:
    meta = TOPICS[topic]
    return {
        "topic": topic,
        "headline": meta["headline"],
        "numbers": _DATA[topic],
        "provenance": {
            "whitepaper_section": meta["whitepaper_section"],
            "source_files": meta["source_files"],
        },
        "caveat": CAVEAT,
    }
