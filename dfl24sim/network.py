"""
dfl24sim.network — the social graph over which FOMO / herding propagates.

Built for scale: graphs are generated in near-linear time and stored as a sparse
CSR adjacency, so contagion is a single sparse matrix-vector product regardless of
population size. Three topologies are supported; the default is a scale-free graph
with influencer hubs and literacy homophily, which is the realistic structure for a
retail crypto community (a few high-degree influencers, assortative mixing).
"""
from __future__ import annotations
import numpy as np
import scipy.sparse as sp

from .config import NetworkParams


def _preferential_attachment(n, m, rng, literacy=None, homophily=0.0):
    """Fast Barabasi-Albert-style growth with optional literacy homophily.

    Uses the endpoint-copying trick: an array of node endpoints in which each node
    appears once per incident edge, so a uniform random draw is degree-proportional.
    With probability `homophily` an attachment instead targets a node close in the
    literacy ordering, producing assortative mixing. O(n*m).
    """
    m = max(1, m)
    src = np.empty(n * m, dtype=np.int64)
    dst = np.empty(n * m, dtype=np.int64)
    endpoints = list(range(m + 1))           # seed clique endpoints
    # literacy-sorted order for homophilous attachment
    if literacy is not None and homophily > 0:
        order = np.argsort(literacy)
        rank = np.empty(n, dtype=np.int64); rank[order] = np.arange(n)
    e = 0
    for v in range(m + 1, n):
        targets = set()
        attempts = 0
        while len(targets) < m and attempts < m * 5:
            attempts += 1
            if literacy is not None and homophily > 0 and rng.random() < homophily:
                # pick a node near v in literacy rank (local window)
                r = rank[v]
                w = int(np.clip(r + rng.integers(-40, 41), 0, n - 1))
                cand = int(order[w])
            else:
                cand = int(endpoints[rng.integers(0, len(endpoints))])
            if cand != v:
                targets.add(cand)
        for t in targets:
            src[e] = v; dst[e] = t
            endpoints.append(v); endpoints.append(t)
            e += 1
    return src[:e], dst[:e]


def _small_world(n, k, rng, rewire_p):
    """Watts-Strogatz ring lattice with rewiring (vectorised ring + random rewire)."""
    k = max(2, (k // 2) * 2)
    base = np.arange(n)
    src_list, dst_list = [], []
    for j in range(1, k // 2 + 1):
        src_list.append(base); dst_list.append((base + j) % n)
    src = np.concatenate(src_list); dst = np.concatenate(dst_list)
    rewire = rng.random(src.shape) < rewire_p
    dst = dst.copy()
    dst[rewire] = rng.integers(0, n, size=rewire.sum())
    keep = src != dst
    return src[keep], dst[keep]


def build_graph(n, params: NetworkParams, rng, literacy=None):
    """Return a row-normalised sparse CSR adjacency A_norm and the degree vector.

    Contagion signal for a behaviour vector x is simply  A_norm @ x.
    """
    if params.kind == "small_world":
        src, dst = _small_world(n, params.mean_degree, rng, params.rewire_p)
    elif params.kind == "random":
        ne = n * params.mean_degree // 2
        src = rng.integers(0, n, ne); dst = rng.integers(0, n, ne)
        keep = src != dst; src, dst = src[keep], dst[keep]
    else:  # scale_free (default)
        src, dst = _preferential_attachment(n, max(1, params.mean_degree // 2),
                                            rng, literacy, params.homophily)
    # symmetric adjacency
    data = np.ones(len(src) * 2, dtype=np.float32)
    rows = np.concatenate([src, dst]); cols = np.concatenate([dst, src])
    A = sp.csr_matrix((data, (rows, cols)), shape=(n, n))
    A.sum_duplicates()
    A.data[:] = 1.0                           # binarise
    deg = np.asarray(A.sum(axis=1)).ravel()
    inv = np.where(deg > 0, 1.0 / deg, 0.0)
    A_norm = sp.diags(inv.astype(np.float32)) @ A
    return A_norm.tocsr(), deg


def degree_stats(deg):
    d = deg[deg > 0]
    if d.size == 0:
        return {}
    return {"mean_degree": float(d.mean()), "max_degree": int(d.max()),
            "p99_degree": float(np.percentile(d, 99)),
            "isolated_frac": float((deg == 0).mean())}
