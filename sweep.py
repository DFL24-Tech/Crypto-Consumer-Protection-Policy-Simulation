"""Sensitivity sweeps: vary one mechanism at a time, all else baseline, to test
which conclusions in the white paper survive. Writes results/sensitivity/sweeps.json.
Run:  python sweep.py
"""
import json, numpy as np, sys
from dataclasses import replace
from dfl24sim import SimConfig, run
from dfl24sim import scenarios as sc

SEEDS=(0,1); N=6000; STEPS=14; NC=8000
CAL=dict(fric_attention=1.13, hab_lr=0.228)
def base_cfg(sd,**bov):
    c=SimConfig(n_agents=N,steps=STEPS,seed=sd)
    return c.with_(behavior=replace(c.behavior,**{**CAL,**bov}))
def fr_fade(out):
    ss=out["summary"]["step_series"]; by={}
    for r in ss: by[(r["step"],r["arm"])]=r["high_risk_rate"]
    st=sorted({k[0] for k in by})
    c0,f0=by[(st[0],"control")],by[(st[0],"friction")]
    cL,fL=by[(st[-1],"control")],by[(st[-1],"friction")]
    r0=(c0-f0)/c0 if c0 else 0; rL=(cL-fL)/cL if cL else 0
    return r0,((rL/r0) if r0>1e-6 else 0)
def det_sybil(out):
    d=out["summary"]["detection_counts_by_role"]["sybil_attacker"]; return d[0]/max(d[1],1)
def mean(xs): return float(np.mean(xs))
R={}

# 1) phi -> first-exposure reduction
s=[]
for phi in [0.6,0.9,1.13,1.4,1.7]:
    s.append((phi, mean([fr_fade(run(base_cfg(sd,fric_attention=phi)))[0] for sd in SEEDS])))
R["phi_firstreduction"]=s; print("S1 phi:",[(p,round(v,3)) for p,v in s]); sys.stdout.flush()

# 2) eta -> fade ratio
s=[]
for eta in [0.0,0.1,0.228,0.4,0.6]:
    s.append((eta, mean([fr_fade(run(base_cfg(sd,hab_lr=eta)))[1] for sd in SEEDS])))
R["eta_faderatio"]=s; print("S2 eta:",[(e,round(v,3)) for e,v in s]); sys.stdout.flush()

# 3) bandit eps -> sybil detection (+ static ref)
static_ref=mean([det_sybil(run(sc.build("B4_adaptive_red_team",NC,STEPS,sd).with_(adaptive_adversary=False))) for sd in SEEDS])
s=[]
for e in [0.05,0.15,0.25,0.4]:
    s.append((e, mean([det_sybil(run(sc.build("B4_adaptive_red_team",NC,STEPS,sd).with_(adaptive_adversary=True,bandit_epsilon=e))) for sd in SEEDS])))
R["eps_sybildet"]={"static_ref":static_ref,"adaptive":s}; print("S3 static=",round(static_ref,3),"adaptive:",[(e,round(v,3)) for e,v in s]); sys.stdout.flush()

# 4) trust_false_alarm -> over-friction trust vs standard(tiered) ref
trust_std=mean([sc._metrics(run(sc.build("D3_vifc_tiered_sandbox",N,STEPS,sd)))["final_trust"] for sd in SEEDS])
s=[]
for fa in [0.0,0.05,0.1,0.2]:
    rs=[]
    for sd in SEEDS:
        c=sc.build("D2_over_friction_fatigue",N,STEPS,sd); c=c.with_(behavior=replace(c.behavior,trust_false_alarm=fa))
        rs.append(sc._metrics(run(c))["final_trust"])
    s.append((fa, mean(rs)))
R["fa_overfrictiontrust"]={"standard_ref":trust_std,"overfriction":s}; print("S4 std_trust=",round(trust_std,3),"overfric:",[(f,round(v,3)) for f,v in s]); sys.stdout.flush()

# 5) groom_strength -> victim reduction
s=[]
for g in [0.0,0.1,0.2,0.35,0.5]:
    rs=[]
    for sd in SEEDS:
        c=sc.build("C1_pig_butchering_wave",N,STEPS,sd); c=c.with_(behavior=replace(c.behavior,groom_strength=g))
        m=sc._metrics(run(c)); vc,vf=m["victim_take_control"],m["victim_take_friction"]
        rs.append((vc-vf)/vc if vc>1e-6 else 0)
    s.append((g, mean(rs)))
R["groom_victimreduction"]=s; print("S5 groom:",[(g,round(v,3)) for g,v in s]); sys.stdout.flush()

# 6) maint_margin -> liquidated_frac, drawdown
s=[]
for mm in [0.3,0.45,0.6,0.75]:
    lf=[];dd=[]
    for sd in SEEDS:
        c=sc.build("A3_crash_cascade",N,STEPS,sd); c=c.with_(market=replace(c.market,maint_margin=mm))
        m=sc._metrics(run(c)); lf.append(m["liquidated_frac"]); dd.append(m["trough_drawdown"])
    s.append((mm, mean(lf), mean(dd)))
R["margin_systemic"]=s; print("S6 margin:",[(m,round(l,3),round(d,3)) for m,l,d in s]); sys.stdout.flush()

json.dump(R, open("results/sensitivity/sweeps.json","w"), indent=1)
print("SAVED results/sensitivity/sweeps.json")
