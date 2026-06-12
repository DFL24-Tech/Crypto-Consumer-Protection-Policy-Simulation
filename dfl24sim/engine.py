"""
dfl24sim.engine — the vectorised simulation loop.

One step updates the entire population with array operations: contagion over the
sparse social graph, dual-process decisions with a coupled friction counterfactual,
a vectorised policy judgement, adaptive-adversary tactic selection, endogenous market
settlement, and RL/trust learning. No Python loop over agents anywhere in the hot path.

Scenario mechanisms (all off by default, so the calm baseline is unchanged): market
regime drift, exogenous price shocks, leverage liquidation cascades, social-engineering
grooming over the network, false-positive alert fatigue, and a tiered policy.
"""
from __future__ import annotations
import numpy as np

from .config import (SimConfig, MANIPULATOR, SYBIL, LAUNDERER, CYBER,
                     CLEAN, SPECULATOR, ADV_NAME_LIST, ROLE_NAMES)
from .population import build_population
from .network import build_graph, degree_stats
from .market import PriceBook
from . import behavior as bh
from . import policy as pol


def _time_pressure(step, steps, rng):
    base = 0.3 + 0.5 * (step / max(steps - 1, 1))
    return float(np.clip(base + rng.normal(0, 0.05), 0, 1))


def run(cfg: SimConfig, rng=None, record_panel=True):
    rng = rng or np.random.default_rng(cfg.seed)
    st = build_population(cfg, rng)
    A_norm, deg = build_graph(cfg.n_agents, cfg.network, rng, literacy=st.literacy)
    book = PriceBook(cfg.market, cfg.n_agents, cfg.steps)
    B, MP, PP, POP = cfg.behavior, cfg.market, cfg.policy, cfg.population
    n = cfg.n_agents

    adv_idx = np.where(st.is_adv)[0]
    bandits = pol.AdversaryBandits(st.role[adv_idx], adv_idx, cfg.bandit_epsilon, rng)
    sybil_total = int((st.role == SYBIL).sum())

    is_manip = st.role == MANIPULATOR
    is_sybil = st.role == SYBIL
    is_laund = st.role == LAUNDERER
    is_cyber = st.role == CYBER
    honest = ~st.is_adv
    laund_accum = np.zeros(n)

    # ---- scenario setup ----
    is_scammer = np.zeros(n, dtype=bool)
    groom_signal = np.zeros(n)
    if POP.scammer_frac > 0:
        is_scammer = (rng.random(n) < POP.scammer_frac) & honest
        groom_signal = np.asarray(A_norm @ is_scammer.astype(np.float64)).ravel()
    victim = honest & ~is_scammer & (groom_signal > 0)

    if PP.tiered:
        tier = 1 + (st.literacy >= 33).astype(int) + (st.literacy >= 66).astype(int)
        fric_mult = np.select([tier == 1, tier == 2, tier == 3], [1.5, 1.0, 0.0], 1.0)
        gated_pre = tier == 3
    else:
        fric_mult = None
        gated_pre = (st.literacy >= PP.gate_literacy) & (st.credits >= PP.gate_credits)

    extra_drift = MP.bull_drift - MP.crash_drift
    liquidated = np.zeros(n, dtype=bool)
    liq_overhang = 0.0

    det_num = {r: 0 for r in ADV_NAME_LIST}
    det_den = {r: 0 for r in ADV_NAME_LIST}
    agg = dict(friction_fired=0, friction_on_high_risk=0, friction_on_safe=0,
               high_risk_attempts=0, adversary_actions=0, blocked_adversary=0,
               false_positives=0, aml_flags=0)
    step_series, victim_series, panel_first = [], [], None

    for step in range(cfg.steps):
        tp = _time_pressure(step, cfg.steps, rng)
        social = np.asarray(A_norm @ st.last_action).ravel() * MP.contagion_mult

        if B.groom_strength > 0:
            st.belief = st.belief + B.groom_strength * groom_signal
            coached = groom_signal > 0
            # scammers coach victims to discount platform warnings: the prompt's
            # salience erodes, so point-of-action friction loses its grip on them
            st.salience[coached] = np.maximum(0.08, st.salience[coached] * (1.0 - 0.18))

        if not PP.tiered:
            gated_pre = (st.literacy >= PP.gate_literacy) & (st.credits >= PP.gate_credits)
        friction_shows = (st.arm == 1) & ~gated_pre
        if PP.friction_off:
            friction_shows = np.zeros(n, dtype=bool)

        p1, p0, w = bh.decision_probs(st, social, tp, fired=friction_shows, B=B,
                                      fric_mult=fric_mult)
        u = rng.random(n)
        attempt = (u < p0) & honest
        took = np.where(friction_shows, u < p1, u < p0) & honest
        backed_out = honest & friction_shows & attempt & ~took
        lev_take = took & (rng.random(n) < 0.4)
        action_code = np.zeros(n, dtype=np.int64)
        action_code[took] = 1
        action_code[lev_take] = 2
        st.took_leverage |= lev_take

        tactic = np.zeros(n, dtype=np.int64)
        if adv_idx.size:
            tactic[adv_idx] = bandits.select(cfg.adaptive_adversary)
            action_code[is_manip] = 3
            action_code[is_sybil] = 4
            action_code[is_laund] = 5
            action_code[is_cyber] = 1

        transfers = np.zeros(n); amount = np.full(n, 500.0)
        order_burst = np.zeros(n, dtype=np.int64); cancel_rate = np.zeros(n)
        sanctions = np.zeros(n, dtype=bool); pep = np.zeros(n, dtype=bool)
        step_add = np.where(tactic[is_laund] == 0, 1.0, 0.35)
        laund_accum[is_laund] += step_add
        transfers[is_laund] = laund_accum[is_laund]
        amount[is_laund] = np.where(tactic[is_laund] >= 2, PP.struct_amount + 500, 1500.0)
        manip_naive = is_manip & (tactic == 0)
        burst_hi = manip_naive & (rng.random(n) < 0.5)
        order_burst[burst_hi] = PP.velocity_burst + 4
        order_burst[manip_naive & ~burst_hi] = PP.velocity_burst - 6
        order_burst[is_manip & (tactic >= 1)] = PP.velocity_burst - 5
        cancel_rate[is_manip & (tactic == 1)] = PP.cancel_rate + 0.1

        decision = pol.judge(st, action_code, tactic,
                             {"transfers_24h": transfers, "amount": amount,
                              "order_burst": order_burst, "cancel_rate": cancel_rate,
                              "sanctions": sanctions, "pep": pep},
                             PP, cluster_size=np.full(n, sybil_total))
        high_risk = decision["high_risk"]
        flagged = decision["flagged"] & (not PP.policy_off)

        fired_real = high_risk & friction_shows
        fp_fire = np.zeros(n, dtype=bool)
        if PP.false_positive_rate > 0:
            # false alarms hit benign, active users (not taking the high-risk action)
            fp_fire = (honest & friction_shows & ~took
                       & (rng.random(n) < PP.false_positive_rate))
            agg["false_positives"] += int(fp_fire.sum())
        fired = fired_real | fp_fire            # for precision / on-safe bookkeeping

        manip_p = book.campaign_pressure(MP.manip_pressure, step)
        sybil_p = book.campaign_pressure(MP.sybil_pressure, step)
        pressure = np.zeros(n)
        pressure[is_manip] = manip_p
        pressure[is_sybil] = sybil_p
        pressure[lev_take] += st.leverage[lev_take] * 0.2
        pressure[took & ~lev_take] += 1.0
        net_pressure = float(pressure.sum()) - liq_overhang
        ret = book.settle(net_pressure, rng, extra_drift)
        if step == MP.shock_step and MP.shock_size != 0.0:
            pre = book.price
            book.apply_shock(MP.shock_size)
            ret += (book.price - pre) / max(pre, 1e-6)

        chaser_pnl = np.zeros(n)
        chaser_pnl[lev_take] = np.clip(st.leverage[lev_take] * ret, -1.0, 3.0)
        st.hr_leverage_pnl[lev_take] += chaser_pnl[lev_take]

        if MP.liquidation:
            newly_liq = st.took_leverage & (st.hr_leverage_pnl < -MP.maint_margin) & ~liquidated
            liquidated |= newly_liq
            liq_overhang = float(newly_liq.sum()) * MP.liq_pressure
        else:
            liq_overhang = 0.0

        outcome = np.zeros(n)
        outcome[took & ~lev_take] = rng.normal(0.4 * ret, 0.12, int((took & ~lev_take).sum()))
        outcome[lev_take] = chaser_pnl[lev_take]
        outcome[~took] = rng.normal(0.5 * ret, 0.10, int((~took).sum()))

        bh.update_learning(st, fired_real, took, outcome, high_risk, B)
        if fp_fire.any():
            # alert fatigue: false alarms erode trust and habituate the prompt (cry wolf)
            st.trust[fp_fire] = np.clip(st.trust[fp_fire] - B.trust_false_alarm, 0.0, 1.0)
            st.salience[fp_fire] = (1 - B.hab_lr) * st.salience[fp_fire]
        if adv_idx.size:
            bandits.reward(~flagged[adv_idx])

        agg["friction_fired"] += int(fired.sum())
        agg["friction_on_high_risk"] += int((fired & high_risk).sum())
        agg["friction_on_safe"] += int((fired & ~high_risk).sum())
        agg["high_risk_attempts"] += int((attempt | (high_risk & st.is_adv)).sum())
        agg["aml_flags"] += int(flagged.sum())
        for code, name in ((MANIPULATOR, "market_manipulator"), (SYBIL, "sybil_attacker"),
                           (LAUNDERER, "money_launderer"), (CYBER, "cyber_red_team")):
            mask = st.role == code
            det_den[name] += int(mask.sum())
            det_num[name] += int(flagged[mask].sum())
        agg["adversary_actions"] += int(st.is_adv.sum())
        agg["blocked_adversary"] += int(flagged[st.is_adv].sum())

        for arm_val, arm_name in ((0, "control"), (1, "friction")):
            m = honest & (st.arm == arm_val)
            step_series.append({"step": step, "arm": arm_name,
                                "high_risk_rate": float(took[m].mean()) if m.any() else 0.0})
        if victim.any():
            for arm_val, arm_name in ((0, "control"), (1, "friction")):
                m = victim & (st.arm == arm_val)
                victim_series.append({"step": step, "arm": arm_name,
                                      "take_rate": float(took[m].mean()) if m.any() else 0.0})

        st.last_action = took.astype(np.float64)
        st.last_w = w
        if record_panel and step == 0:
            panel_first = _snapshot(st, w, took, fired, attempt, backed_out)

    summary = _summarise(cfg, st, book, agg, det_num, det_den, deg, step_series, sybil_total)
    summary["liquidated_frac"] = float(liquidated.sum() / max(st.took_leverage.sum(), 1))
    summary["scam_victim_frac"] = float(victim.mean())
    summary["final_trust"] = float(st.trust.mean())
    summary["victim_series"] = victim_series
    summary["false_positive_count"] = agg["false_positives"]
    return {"summary": summary, "panel_first": panel_first, "state": st, "book": book}


def _snapshot(st, w, took, fired, attempt, backed):
    return dict(
        literacy=st.literacy.copy(), numeracy=st.numeracy.copy(),
        impulsivity=st.impulsivity.copy(), risk=st.risk.copy(), trust=st.trust.copy(),
        arm=st.arm.copy(), is_adv=st.is_adv.copy(), w_deliberate=w.copy(),
        took=took.copy(), fired=fired.copy(), attempt=attempt.copy(), backed_out=backed.copy(),
    )


def _summarise(cfg, st, book, agg, det_num, det_den, deg, step_series, sybil_total):
    detection = {r: (det_num[r], det_den[r]) for r in det_num if det_den[r] > 0}
    path = book.history
    return dict(
        n_agents=cfg.n_agents, steps=cfg.steps, seed=cfg.seed,
        adaptive_adversary=cfg.adaptive_adversary,
        friction_precision=agg["friction_on_high_risk"] / max(agg["friction_fired"], 1),
        friction_on_safe=agg["friction_on_safe"],
        high_risk_attempts=agg["high_risk_attempts"], aml_flags=agg["aml_flags"],
        adversary_detection=agg["blocked_adversary"] / max(agg["adversary_actions"], 1),
        detection_counts_by_role=detection,
        final_price=path[-1], max_price=max(path), min_price=min(path), price_path=path,
        network=degree_stats(deg), sybil_cluster=sybil_total, step_series=step_series,
    )
