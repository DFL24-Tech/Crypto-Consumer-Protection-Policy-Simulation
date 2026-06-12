"""
dfl24sim.config — typed, immutable configuration for the whole platform.

Every tunable lives in one of these frozen dataclasses so that experiments are
fully described by a single Config object (serialisable to/from YAML), and the
global sensitivity / calibration layers can perturb a well-defined vector. There
are no magic numbers buried in the engine.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict, replace
from typing import Optional
import json


@dataclass(frozen=True)
class BehaviorParams:
    """Coefficients of the dual-process behavioural model (see MODEL.md)."""
    # System 1 (fast, affective)
    s1_intercept: float = -0.55
    s1_risk_app: float = 2.2
    s1_social: float = 1.5
    s1_arousal_gain: float = 1.1
    # System 2 (slow, deliberate)
    s2_pt_gain: float = 0.55
    s2_literacy_acc: float = 1.1
    s2_belief: float = 0.5
    # arbitration (probability System 2 controls)
    arb_intercept: float = -0.2
    arb_literacy: float = 1.8
    arb_numeracy: float = 1.0
    arb_impulsivity: float = 1.5
    arb_trust: float = 0.5
    arb_time_pressure: float = 0.8
    # friction as attention
    fric_attention: float = 1.1
    fric_cost_floor: float = 0.05
    # habituation (reinforcement learning on prompt salience)
    hab_lr: float = 0.18
    hab_recovery: float = 0.05
    hab_badoutcome_protect: float = 0.7
    # trust dynamics (UTAUT2 mediator)
    trust_lr: float = 0.25
    trust_outcome: float = 0.3
    trust_true_positive: float = 0.15
    trust_false_alarm: float = 0.1
    # prospect theory
    pt_alpha: float = 0.88
    pt_lambda: float = 2.25
    pt_gamma: float = 0.61
    # social-engineering grooming (pig-butchering): belief boost per step for a
    # victim from each scammer neighbour (0 disables the channel)
    groom_strength: float = 0.0


@dataclass(frozen=True)
class MarketParams:
    """Endogenous Kyle-style price with a coordinated pump-and-dump campaign."""
    fundamental: float = 1.0
    kappa: float = 0.15            # reversion speed
    lam_impact: float = 0.0006    # Kyle lambda at unit depth
    noise_sd: float = 0.010
    depth_ref: float = 1000.0     # depth = N / depth_ref (population invariance)
    turn_frac: float = 0.55       # accumulate before this fraction, then distribute
    dump_intensity: float = 2.0
    manip_pressure: float = 6.0
    sybil_pressure: float = 4.0
    leverage_min: int = 2
    leverage_max: int = 12
    # market regime and exogenous dynamics
    regime: str = "calm"          # calm | bull | crash
    bull_drift: float = 0.0       # extra per-step upward drift (mania)
    crash_drift: float = 0.0      # extra per-step downward drift (bear)
    contagion_mult: float = 1.0   # multiplier on the herding signal (mania amplifies)
    shock_step: int = -1          # step at which to inject an exogenous price shock
    shock_size: float = 0.0       # fractional shock (e.g. -0.40 = a 40% depeg)
    # leverage liquidation cascade
    liquidation: bool = False     # enable margin calls / forced selling
    maint_margin: float = 0.6     # liquidated once cumulative levered loss exceeds this
    liq_pressure: float = 3.0     # forced-sell flow per liquidated chaser


@dataclass(frozen=True)
class PolicyParams:
    """Thresholds of the compliance policy (mirrors the OPA/Rego program)."""
    gate_literacy: float = 75.0
    gate_credits: int = 3
    struct_count_24h: int = 8      # structuring: transfers to a beneficiary in 24h
    struct_amount: float = 3000.0
    velocity_burst: int = 12       # market-integrity: order burst
    cancel_rate: float = 0.7       # spoofing proxy
    sybil_cluster: int = 20        # coordinated cluster size that trips the rule
    # scenario levers
    false_positive_rate: float = 0.0  # benign actions wrongly prompted (alert fatigue)
    tiered: bool = False              # 3-tier sandbox: friction/gating depend on tier
    friction_off: bool = False        # disable friction entirely (laissez-faire)
    policy_off: bool = False          # disable compliance flags entirely


@dataclass(frozen=True)
class NetworkParams:
    """Social graph topology. Contagion (FOMO) propagates over this graph."""
    kind: str = "scale_free"       # scale_free | small_world | random
    mean_degree: int = 8           # target average degree
    homophily: float = 0.6         # 0..1, assortativity by literacy
    rewire_p: float = 0.1          # small-world rewiring probability
    influencer_frac: float = 0.01  # fraction that are high-degree hubs


@dataclass(frozen=True)
class PopulationParams:
    literacy_mean: float = 42.0
    literacy_sd: float = 18.0
    adversary_mix: float = 0.10
    # role split WITHIN the adversary minority (must sum to ~1)
    p_manipulator: float = 0.33
    p_sybil: float = 0.34
    p_launderer: float = 0.22
    p_cyber: float = 0.11
    young_frac: float = 0.75       # share under 35 (stated user base)
    scammer_frac: float = 0.0      # fraction acting as social-engineering scammers


@dataclass(frozen=True)
class SimConfig:
    n_agents: int = 5000
    steps: int = 14
    seed: int = 0
    adaptive_adversary: bool = True
    bandit_epsilon: float = 0.15
    track_price: bool = True
    behavior: BehaviorParams = field(default_factory=BehaviorParams)
    market: MarketParams = field(default_factory=MarketParams)
    policy: PolicyParams = field(default_factory=PolicyParams)
    network: NetworkParams = field(default_factory=NetworkParams)
    population: PopulationParams = field(default_factory=PopulationParams)

    # ---- serialisation ----
    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @staticmethod
    def from_dict(d: dict) -> "SimConfig":
        sub = dict(d)
        for k, cls in [("behavior", BehaviorParams), ("market", MarketParams),
                       ("policy", PolicyParams), ("network", NetworkParams),
                       ("population", PopulationParams)]:
            if k in sub and isinstance(sub[k], dict):
                sub[k] = cls(**sub[k])
        return SimConfig(**sub)

    def with_(self, **kw) -> "SimConfig":
        return replace(self, **kw)


# role codes (int for vectorised arrays)
CLEAN, SPECULATOR, MANIPULATOR, SYBIL, LAUNDERER, CYBER = 0, 1, 2, 3, 4, 5
ROLE_NAMES = {CLEAN: "clean_retail", SPECULATOR: "uninformed_speculator",
              MANIPULATOR: "market_manipulator", SYBIL: "sybil_attacker",
              LAUNDERER: "money_launderer", CYBER: "cyber_red_team"}
ADVERSARY_ROLES = (MANIPULATOR, SYBIL, LAUNDERER, CYBER)
ADV_NAME_LIST = ("market_manipulator", "sybil_attacker", "money_launderer", "cyber_red_team")
