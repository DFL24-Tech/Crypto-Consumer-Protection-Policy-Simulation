"""Morris elementary-effects screening over 7 parameters x 4 outputs.
Writes results/gsa/morris.json. Run: python gsa_morris.py"""
import json, numpy as np
from dataclasses import replace
from dfl24sim import SimConfig, run
from dfl24sim import scenarios as sc
from SALib.sample.morris import sample as morris_sample
from SALib.analyze import morris as morris_analyze

N=3000; STEPS=12
NAMES=["phi","eta","theta_fa","epsilon","maint_margin","arb_intercept","beta_r"]
BOUNDS=[[0.6,1.7],[0.0,0.6],[0.0,0.2],[0.05,0.4],[0.3,0.75],[-0.5,0.1],[1.5,3.0]]
problem={"num_vars":len(NAMES),"names":NAMES,"bounds":BOUNDS}

def fr_fade(out):
    ss=out["summary"]["step_series"]; by={}
    for r in ss: by[(r["step"],r["arm"])]=r["high_risk_rate"]
    st=sorted({k[0] for k in by})
    c0,f0=by[(st[0],"control")],by[(st[0],"friction")]
    cL,fL=by[(st[-1],"control")],by[(st[-1],"friction")]
    r0=(c0-f0)/c0 if c0 else 0; rL=(cL-fL)/cL if cL else 0
    return r0,((rL/r0) if r0>1e-6 else 0)

def model(x):
    phi,eta,tfa,eps,mm,arb,br=[float(v) for v in x]
    cfg=sc.build("D2_over_friction_fatigue",N,STEPS,0).with_(adaptive_adversary=True,bandit_epsilon=eps)
    cfg=cfg.with_(behavior=replace(cfg.behavior,fric_attention=phi,hab_lr=eta,
                  trust_false_alarm=tfa,arb_intercept=arb,s1_risk_app=br))
    cfg=cfg.with_(market=replace(cfg.market,maint_margin=mm))
    s=run(cfg)["summary"]
    r0,fade=fr_fade(run(cfg)) if False else fr_fade({"summary":s})
    d=s["detection_counts_by_role"]["sybil_attacker"]; cov=d[0]/max(d[1],1)
    return [r0,fade,cov,s["final_trust"]]

X=morris_sample(problem,N=12,num_levels=6)
print("Morris runs:",len(X))
Y=np.array([model(x) for x in X])
OUT=["first_reduction","fade_ratio","sybil_coverage","final_trust"]
res={}
for j,o in enumerate(OUT):
    Si=morris_analyze.analyze(problem,X,Y[:,j],num_levels=6)
    res[o]={"names":NAMES,"mu_star":[float(v) for v in Si["mu_star"]],"sigma":[float(v) for v in Si["sigma"]]}
    top=sorted(zip(NAMES,Si["mu_star"]),key=lambda t:-t[1])[:3]
    print(f"{o:16s} top: "+", ".join(f"{n}={v:.3f}" for n,v in top))
json.dump(res,open("results/gsa/morris.json","w"),indent=1)
print("SAVED results/gsa/morris.json")