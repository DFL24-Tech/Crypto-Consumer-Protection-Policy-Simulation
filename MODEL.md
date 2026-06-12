# DFL24-Sim v3 — Model specification

All quantities below are computed as array operations over the whole population each
step (struct-of-arrays). Coefficients live in `config.BehaviorParams`,
`MarketParams`, `PolicyParams`, `NetworkParams`. Notation: for agent *i* at step *t*,
L=literacy, n=numeracy, m=impulsivity, r=risk appetite, T=trust, s=prompt salience,
λ=loss aversion, b=prior belief, τ=time pressure, g=social signal.

## 1. Social graph and contagion

The population lives on a sparse graph **A** (default: scale-free via preferential
attachment with literacy homophily and influencer hubs). Let **Â** be the
row-normalised adjacency. The herding / FOMO signal each step is the neighbour mean of
last step's high-risk indicator **x**:

> (1)  g = Â x          (one sparse matrix–vector product, O(edges))

## 2. Dual-process valuation

**System 1** (fast, affective), with arousal rising in time pressure:

> (2)  arousal = γ₁ (0.6 + 0.4 τ)
> (3)  U₁ = β₀ + β_r r + β_s g + arousal · (0.5 + 0.5 r)

**System 2** (slow, deliberate) prices the opportunity as a prospect-theory lottery.
With value function v and probability weighting w (Tversky–Kahneman):

> (4)  v(z) = z^α            if z ≥ 0;     −λ (−z)^α   if z < 0
> (5)  w(p) = p^γ / (p^γ + (1−p)^γ)^{1/γ}
> (6)  p_win = 0.15 + 0.05 r
> (7)  V = w(p_win) · v(+2) + (1 − w(p_win)) · v(−1)
> (8)  acc = σ( a_L (L/100 − 0.3) + 0.6 n )         (deliberation accuracy)
> (9)  U₂ = c_V · acc · V + c_b · tanh(b)

Because v prices the downside with λ≈2.25, a competent System 2 typically assigns the
high-risk action a **negative** valuation; System 1 may still favour it.

## 3. Arbitration and friction as attention

The probability that System 2 governs the decision:

> (10)  z_w = a₀ + a_L(L/100 − ½) + a_n(n − ½) − a_m(m − ½) + a_T(T − ½) − a_τ τ + Δ
> (11)  w_S2 = σ(z_w)

Friction is **not** a multiplier on the outcome; it is an additive attention boost in
the arbitration, scaled by the (learned) salience of the prompt:

> (12)  Δ = φ · (f₀ + (1 − f₀) · s)       when the prompt fires, else Δ = 0

The probability of taking the high-risk action mixes the two systems:

> (13)  P(take) = w_S2 · σ(U₂) + (1 − w_S2) · σ(U₁)

The **coupled counterfactual** evaluates (13) with Δ and with Δ=0 under common random
numbers, so the per-agent treatment effect is identified without between-arm noise.

## 4. Learning

**Habituation** (Rescorla–Wagner on the prompt's salience s), with re-sensitisation
after a bad click-through and decay after a harmless one:

> (14)  click-through, bad outcome:  s ← (1−η)s + η·min(1, s + ρ(1−s))
> (15)  click-through, ok outcome:   s ← (1−η)s
> (16)  backed out:                  s ← (1−0.3η)s + 0.3η ;  credits ← credits + 1
> (17)  not shown:                   s ← min(1, s + κ_r(1−s))

**Trust** (UTAUT2 mediator) responds to outcomes, true positives (a prompt that
prevented a bad action), and false alarms:

> (18)  ΔT = θ_o tanh(outcome) + θ_tp · 1[prevented] − θ_fa · 1[false alarm]
> (19)  T ← (1−η_T) T + η_T (T + ΔT)

## 5. Endogenous market

Single-asset price P with additive Kyle impact, mean reversion to fundamental F, and a
coordinated pump-and-dump campaign. Depth D = N / D_ref scales with population:

> (20)  campaign(t) = +c           for t < f·H;   −c · d   for t ≥ f·H
> (21)  Flow_t = Σ_i pressure_{i,t}            (manipulator/sybil campaign + leverage longs)
> (22)  P_{t+1} = max(ε, P_t + κ(F − P_t) + (λ_K/D)·Flow_t + P_t·ξ·N(0,1))
> (23)  levered chaser P&L = clip( leverage · ΔP/P , −1, 3 )

## 6. Compliance policy (vectorised mirror of the OPA/Rego program)

High-risk classification, competence gating, friction firing, and flags — all boolean
array rules:

> (24)  high_risk = action ∈ {risky menu}
> (25)  gated_out = (L ≥ L*) ∧ (credits ≥ k*)
> (26)  friction_fires = high_risk ∧ (arm = friction) ∧ ¬gated_out
> (27)  flag = structuring ∨ velocity_burst ∨ spoofing ∨ sybil_cluster ∨ sanctions/PEP

Adversaries select an evasion tactic by a per-agent ε-greedy bandit with optimistic
initialisation; tactic 0 is policy-catchable, higher tactics progressively evade. The
**cyber** role has no covering rule by construction — this is the coverage gap the
study is designed to expose.

## 7. Calibration

The headline behavioural parameters (φ, β_r, η, a₀) are estimated by Simulated Method
of Moments: minimise a weighted distance between simulated moments (first-exposure
reduction, baseline rate, fade ratio) and field-anchored targets (Havakhor et al.'s
8.6–10.5% first-exposure effect). See `calibrate.py`.
