"""
dfl24sim.policy — the compliance policy and the adaptive adversary, vectorised.

The policy mirrors the OPA/Rego program (high-risk classification, competence gating,
friction firing, and AML / market-integrity / sanctions flags) as boolean array
operations, so judging the whole population is O(N). The adaptive adversary maintains
a per-agent Q-table over evasion tactics and selects ε-greedily, also vectorised.
"""
from __future__ import annotations
import numpy as np
from .config import (PolicyParams, MANIPULATOR, SYBIL, LAUNDERER, CYBER)

# number of evasion tactics per adversary role (index 0 = naive, policy-catchable)
N_TACTICS = {MANIPULATOR: 4, SYBIL: 3, LAUNDERER: 4, CYBER: 3}
MAX_TACTICS = 4


class AdversaryBandits:
    """Vectorised epsilon-greedy bandits, one row of Q-values per adversary agent."""

    def __init__(self, roles, idx, epsilon, rng):
        self.idx = idx                              # global indices of adversaries
        self.roles = roles                          # role code per adversary
        self.eps = epsilon
        self.rng = rng
        self.Q = np.ones((idx.size, MAX_TACTICS))   # optimistic init -> forces exploration
        self.counts = np.zeros((idx.size, MAX_TACTICS))
        self.n_tac = np.array([N_TACTICS.get(int(r), 1) for r in roles])
        self._last = np.zeros(idx.size, dtype=np.int64)

    def select(self, adaptive):
        if not adaptive:
            self._last[:] = 0                        # naive tactic
            return self._last
        # exploit: argmax over valid tactics; explore with prob eps
        q = self.Q.copy()
        for k in range(MAX_TACTICS):
            q[self.n_tac <= k, k] = -np.inf
        greedy = q.argmax(axis=1)
        explore = self.rng.random(self.idx.size) < self.eps
        rand = (self.rng.random(self.idx.size) * self.n_tac).astype(np.int64)
        self._last = np.where(explore, rand, greedy)
        return self._last

    def reward(self, executed_unflagged):
        a = self._last
        rows = np.arange(self.idx.size)
        self.counts[rows, a] += 1
        self.Q[rows, a] += (executed_unflagged.astype(float) - self.Q[rows, a]) / self.counts[rows, a]


def classify_high_risk(action_code):
    """High-risk action codes: 1..5 are the risky menu; 0 is benign."""
    return action_code >= 1


def judge(st, action_code, tactic, meta, pp: PolicyParams, cluster_size):
    """Vectorised policy decision.

    Returns dict of boolean arrays: high_risk, gated_out, friction_fire, flagged.
    `meta` carries per-agent features (transfers_24h, amount, order_burst, cancel_rate,
    counterparty_spread, sanctions, pep) as arrays. `tactic` shifts the features an
    adversary exposes (higher tactic = better evasion). `cluster_size` is the live
    sybil cluster size for sybil agents.
    """
    high_risk = classify_high_risk(action_code)
    gated_out = (st.literacy >= pp.gate_literacy) & (st.credits >= pp.gate_credits)
    friction_fire = high_risk & (st.arm == 1) & ~gated_out

    n = st.n
    flagged = np.zeros(n, dtype=bool)

    # --- AML: structuring (launderer) ---
    transfers = meta["transfers_24h"]
    amount = meta["amount"]
    structuring = (transfers >= pp.struct_count_24h) & (amount < pp.struct_amount)
    flagged |= structuring

    # --- market integrity: velocity / spoofing (manipulator) ---
    burst = (meta["order_burst"] >= pp.velocity_burst)
    spoof = (meta["cancel_rate"] >= pp.cancel_rate)
    flagged |= burst | spoof

    # --- sybil cluster rule ---
    is_sybil = st.role == SYBIL
    sybil_caught = is_sybil & (cluster_size >= pp.sybil_cluster) & (tactic == 0)
    flagged |= sybil_caught

    # --- sanctions / PEP ---
    flagged |= meta["sanctions"] | (meta["pep"] & (amount > pp.struct_amount))

    # cyber (bridge abuse) has no covering rule -> remains a coverage gap by design
    return {"high_risk": high_risk, "gated_out": gated_out,
            "friction_fire": friction_fire, "flagged": flagged}
