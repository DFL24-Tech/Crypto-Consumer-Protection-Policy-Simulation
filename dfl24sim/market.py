"""
dfl24sim.market — endogenous price with additive Kyle impact, mean reversion, and a
coordinated pump-and-dump campaign. Depth scales with N so dynamics are population
invariant. Per-agent chaser P&L is read off the realised price path (vectorised).
"""
from __future__ import annotations
import numpy as np
from .config import MarketParams


class PriceBook:
    def __init__(self, mp: MarketParams, n_agents, steps):
        self.mp = mp
        self.price = mp.fundamental
        self.depth = max(n_agents / mp.depth_ref, 1e-3)
        self.steps = max(int(steps), 1)
        self.history = [mp.fundamental]
        self.last_return = 0.0

    def campaign_pressure(self, base, step):
        """+base while accumulating, -base*dump after the turn (bubble then crash)."""
        turn = self.mp.turn_frac * self.steps
        return base if step < turn else -base * self.mp.dump_intensity

    def apply_shock(self, frac):
        """One-off exogenous multiplicative shock to the price (e.g. a depeg)."""
        self.price = max(0.05, self.price * (1.0 + frac))
        self.history[-1] = self.price
        return self.price

    def settle(self, net_pressure, rng, extra_drift=0.0):
        mp = self.mp
        drift = mp.kappa * (mp.fundamental - self.price) + extra_drift * self.price
        impact = (mp.lam_impact / self.depth) * net_pressure
        shock = self.price * mp.noise_sd * rng.normal()
        new = max(0.05, self.price + drift + impact + shock)
        self.last_return = (new - self.price) / max(self.price, 1e-6)
        self.price = new
        self.history.append(new)
        return self.last_return
