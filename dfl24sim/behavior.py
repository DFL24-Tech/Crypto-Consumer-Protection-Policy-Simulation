"""
dfl24sim.behavior — the dual-process behavioural model, vectorised.

Identical equations to the documented model (System-1 affect vs System-2 deliberate
valuation, arbitration weight, friction as attention, RL habituation, UTAUT2 trust),
but every quantity is an array operation over the whole population. See MODEL.md.
"""
from __future__ import annotations
import numpy as np
from .config import BehaviorParams


def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -60, 60)))


def pt_value(x, alpha, lam):
    pos = x >= 0
    out = np.empty_like(x, dtype=np.float64)
    out[pos] = np.power(x[pos], alpha)
    out[~pos] = -lam[~pos] * np.power(-x[~pos], alpha)
    return out


def pt_weight(p, gamma):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return p ** gamma / ((p ** gamma + (1 - p) ** gamma) ** (1.0 / gamma))


def _system1(st, social, tp, B: BehaviorParams):
    arousal = B.s1_arousal_gain * (0.6 + 0.4 * tp)
    return (B.s1_intercept + B.s1_risk_app * st.risk + B.s1_social * social
            + arousal * (0.5 + 0.5 * st.risk))


def _system2(st, B: BehaviorParams):
    p_win = 0.15 + 0.05 * st.risk
    w = pt_weight(p_win, B.pt_gamma)
    gain = pt_value(np.full(st.n, 2.0), B.pt_alpha, st.lam)
    loss = pt_value(np.full(st.n, -1.0), B.pt_alpha, st.lam)
    V = w * gain + (1 - w) * loss
    acc = sigmoid(B.s2_literacy_acc * (st.literacy / 100 - 0.3) + 0.6 * st.numeracy)
    return B.s2_pt_gain * acc * V + B.s2_belief * np.tanh(st.belief)


def _w_deliberate(st, tp, boost, B: BehaviorParams):
    z = (B.arb_intercept
         + B.arb_literacy * (st.literacy / 100 - 0.5)
         + B.arb_numeracy * (st.numeracy - 0.5)
         - B.arb_impulsivity * (st.impulsivity - 0.5)
         + B.arb_trust * (st.trust - 0.5)
         - B.arb_time_pressure * tp
         + boost)
    return sigmoid(z)


def attention_boost(st, B: BehaviorParams):
    return B.fric_attention * (B.fric_cost_floor + (1 - B.fric_cost_floor) * st.salience)


def decision_probs(st, social, tp, fired, B: BehaviorParams, fric_mult=None):
    """Return (p_fired, p_notfired): P(take high-risk) with and without the prompt.

    fired is a boolean array (prompt shown this step). p_fired uses the attention
    boost where fired; p_notfired is the counterfactual with boost=0 everywhere.
    fric_mult optionally scales the attention boost per agent (tiered policy).
    """
    s1 = sigmoid(_system1(st, social, tp, B))
    s2 = sigmoid(_system2(st, B))
    boost = attention_boost(st, B)
    if fric_mult is not None:
        boost = boost * fric_mult
    boost = np.where(fired, boost, 0.0)
    w1 = _w_deliberate(st, tp, boost, B)
    w0 = _w_deliberate(st, tp, np.zeros(st.n), B)
    p1 = w1 * s2 + (1 - w1) * s1
    p0 = w0 * s2 + (1 - w0) * s1
    return p1, p0, w1


def update_learning(st, fired, took, outcome, action_high_risk, B: BehaviorParams):
    """Vectorised RL habituation on salience + UTAUT2 trust update."""
    # ---- prior losses ----
    st.prior_losses += (outcome < 0).astype(np.int64)

    # ---- salience (Rescorla-Wagner on the prompt's attention value) ----
    s = st.salience
    clicked_bad = fired & took & (outcome < 0)
    clicked_ok = fired & took & (outcome >= 0)
    backed = fired & ~took
    not_fired = ~fired
    # clicked through, bad outcome: re-sensitise
    target = np.minimum(1.0, s + B.hab_badoutcome_protect * (1 - s))
    s_new = s.copy()
    s_new[clicked_bad] = (1 - B.hab_lr) * s[clicked_bad] + B.hab_lr * target[clicked_bad]
    # clicked through, fine: decay attention
    s_new[clicked_ok] = (1 - B.hab_lr) * s[clicked_ok]
    # backed out: largely retained + competence credit
    s_new[backed] = (1 - 0.3 * B.hab_lr) * s[backed] + 0.3 * B.hab_lr * 1.0
    st.credits[backed] += 1
    # not shown: slow recovery
    s_new[not_fired] = np.minimum(1.0, s[not_fired] + B.hab_recovery * (1 - s[not_fired]))
    st.salience = np.clip(s_new, 0.0, 1.0)

    # ---- trust (UTAUT2 mediator) ----
    dt = B.trust_outcome * np.tanh(outcome)
    dt += np.where(fired & action_high_risk & ~took, B.trust_true_positive, 0.0)
    dt -= np.where(fired & ~action_high_risk, B.trust_false_alarm, 0.0)
    st.trust = np.clip((1 - B.trust_lr) * st.trust + B.trust_lr * (st.trust + dt), 0.0, 1.0)
