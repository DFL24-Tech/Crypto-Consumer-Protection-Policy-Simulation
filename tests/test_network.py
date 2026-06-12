"""Social graph: scale-free structure with hubs and no isolates."""
import numpy as np
from dfl24sim.network import build_graph, degree_stats
from dfl24sim.config import NetworkParams


def test_scale_free_has_hubs_and_no_isolates():
    rng = np.random.default_rng(0)
    L = rng.normal(42, 18, 10000)
    _, deg = build_graph(10000, NetworkParams(kind="scale_free", mean_degree=8), rng, L)
    st = degree_stats(deg)
    assert st["max_degree"] > 5 * st["mean_degree"]   # heavy-tailed
    assert st["isolated_frac"] == 0.0
