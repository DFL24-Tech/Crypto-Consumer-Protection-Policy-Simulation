"""Shared fixtures and helpers for the DFL24-Sim test suite."""
import numpy as np
import pytest
from dfl24sim import SimConfig, run as run_sim


@pytest.fixture
def small_cfg():
    """A small, fast configuration for unit tests."""
    return SimConfig(n_agents=3000, steps=10, seed=0)


def detection(summary):
    """Detection rate per adversary role from a run summary."""
    return {k: v[0] / max(v[1], 1) for k, v in summary["detection_counts_by_role"].items()}


def run_small(**kw):
    """Run a small simulation, overriding any SimConfig field."""
    base = dict(n_agents=3000, steps=10, seed=0)
    base.update(kw)
    return run_sim(SimConfig(**base))["summary"]
