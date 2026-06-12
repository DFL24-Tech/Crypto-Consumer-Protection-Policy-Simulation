"""
dfl24sim.population — vectorised population as a struct-of-arrays.

Everything an agent has is a column in `State`, so the entire population is updated
with array operations rather than a Python loop over agents. This is what lets the
engine scale to 10^5+ agents.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

from .config import (PopulationParams, SimConfig, CLEAN, SPECULATOR,
                     MANIPULATOR, SYBIL, LAUNDERER, CYBER)


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-z))


@dataclass
class State:
    # fixed traits
    literacy: np.ndarray
    numeracy: np.ndarray
    impulsivity: np.ndarray
    risk: np.ndarray
    lam: np.ndarray
    age: np.ndarray
    concentration: np.ndarray
    role: np.ndarray            # int codes
    arm: np.ndarray             # 0 control, 1 friction
    is_adv: np.ndarray          # bool
    belief: np.ndarray
    # dynamic state
    salience: np.ndarray        # learned attention value of the prompt
    trust: np.ndarray           # UTAUT2 mediator
    credits: np.ndarray         # competence credits
    prior_losses: np.ndarray
    hr_leverage_pnl: np.ndarray
    took_leverage: np.ndarray
    last_action: np.ndarray     # last-step high-risk indicator (for contagion)
    last_w: np.ndarray
    leverage: np.ndarray        # per-agent leverage if they take a levered position

    @property
    def n(self):
        return self.literacy.shape[0]


def build_population(cfg: SimConfig, rng) -> State:
    n = cfg.n_agents
    P = cfg.population
    L = np.clip(rng.normal(P.literacy_mean, P.literacy_sd, n), 0, 100)
    g = (L - P.literacy_mean) / max(P.literacy_sd, 1e-6)          # latent factor
    numeracy = np.clip(_sigmoid(0.9 * g + rng.normal(0, 0.6, n)), 0.01, 0.99)
    impulsivity = np.clip(_sigmoid(-0.7 * g + rng.normal(0, 0.7, n)), 0.01, 0.99)
    risk = np.clip(_sigmoid(-0.5 * g + 0.8 * (impulsivity - 0.5) + rng.normal(0, 0.5, n)), 0.01, 0.99)
    lam = np.clip(2.25 + rng.normal(0, 0.3, n), 1.2, 3.5)
    # demographics: age lognormal tuned so ~young_frac are under 35
    age = np.clip(22 + rng.lognormal(1.7, 0.5, n), 18, 75)
    concentration = rng.beta(5, 2, n)                            # mostly concentrated
    belief = rng.normal(0, 0.4, n)

    # roles: adversary minority split by configured proportions
    role = np.full(n, CLEAN, dtype=np.int64)
    u = rng.random(n)
    is_adv = u < P.adversary_mix
    adv_idx = np.where(is_adv)[0]
    if adv_idx.size:
        probs = np.array([P.p_manipulator, P.p_sybil, P.p_launderer, P.p_cyber])
        probs = probs / probs.sum()
        codes = np.array([MANIPULATOR, SYBIL, LAUNDERER, CYBER])
        role[adv_idx] = rng.choice(codes, size=adv_idx.size, p=probs)
    # honest non-adversaries split clean vs speculator by risk appetite
    honest = ~is_adv
    role[honest & (risk > 0.55)] = SPECULATOR

    arm = (rng.random(n) < 0.5).astype(np.int64)                # randomised assignment
    salience = np.ones(n)
    trust = np.clip(0.5 + 0.2 * g + rng.normal(0, 0.1, n), 0.05, 0.95)  # mild literacy prior
    leverage = rng.integers(cfg.market.leverage_min, cfg.market.leverage_max + 1, n).astype(np.float64)

    z = np.zeros(n)
    return State(
        literacy=L, numeracy=numeracy, impulsivity=impulsivity, risk=risk, lam=lam,
        age=age, concentration=concentration, role=role, arm=arm, is_adv=is_adv,
        belief=belief, salience=salience, trust=trust, credits=np.zeros(n, dtype=np.int64),
        prior_losses=np.zeros(n, dtype=np.int64), hr_leverage_pnl=z.copy(),
        took_leverage=np.zeros(n, dtype=bool), last_action=z.copy(), last_w=z.copy(),
        leverage=leverage,
    )
