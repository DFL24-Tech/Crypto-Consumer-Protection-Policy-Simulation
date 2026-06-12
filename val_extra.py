"""Pattern-oriented validation (stylized facts), Monte-Carlo seed convergence,
and adversary lower bound. Writes results/gsa/validation.json. Run: python val_extra.py"""
import json, numpy as np
from dataclasses import replace
from dfl24sim import SimConfig, run
from dfl24sim import scenarios as sc
R={}

# ---------- A) Stylized facts from a long price path ----------
def stylized(name, steps=300, seed=0):
    cfg=sc.build(name, 8000, steps, seed)
    p=np.asarray(run(cfg)["summary"]["price_path"],float)
    p=p[p>0]; r=np.diff(np.log(p))
    r=r[np.isfinite(r)]
    exk=float(((r-r.mean())**4).mean()/ (r.var()**2) - 3) if r.var()>0 else 0
    ar=r-r.mean(); 
    def acf(x,k): 
        n=len(x); return float(np.corrcoef(x[:-k],x[k:])[0,1]) if n>k+2 else 0
    absr=np.abs(r)
    vcl=[acf(absr,k) for k in (1,2,3,5,10)]
    sgn=acf(r,1)
    return {"n_ret":len(r),"excess_kurtosis":exk,"vol_cluster_acf_abs":vcl,"ret_acf_lag1":sgn}
R["stylized_calm"]=stylized("A1_calm_baseline")
R["stylized_mania"]=stylized("A2_retail_mania")
def shw(d): return {k:(round(v,2) if isinstance(v,float) else ([round(x,2) for x in v] if isinstance(v,list) else v)) for k,v in d.items()}
print("STYLIZED calm:", shw(R["stylized_calm"]))
print("STYLIZED mania:", shw(R["stylized_mania"]))

# ---------- B) Seed convergence + MC standard error ----------
def fr(s):
    by={}
    for x in s["step_series"]: by[(x["step"],x["arm"])]=x["high_risk_rate"]
    st=sorted({k[0] for k in by}); c0,f0=by[(st[0],"control")],by[(st[0],"friction")]
    return (c0-f0)/c0 if c0 else 0
SEEDS=list(range(16))
firsts=[]; covs=[]
for sd in SEEDS:
    s=run(SimConfig(n_agents=6000,steps=14,seed=sd,adaptive_adversary=True))["summary"]
    firsts.append(fr(s)); d=s["detection_counts_by_role"]["sybil_attacker"]; covs.append(d[0]/max(d[1],1))
def conv(xs):
    xs=np.array(xs); rm=[float(xs[:k+1].mean()) for k in range(len(xs))]
    se=[float(xs[:k+1].std(ddof=1)/np.sqrt(k+1)) if k>0 else 0.0 for k in range(len(xs))]
    return rm,se
fm,fse=conv(firsts); cm,cse=conv(covs)
R["convergence"]={"seeds":SEEDS,"first_reduction":firsts,"coverage":covs,
  "first_runmean":fm,"first_se":fse,"cov_runmean":cm,"cov_se":cse,
  "first_final":fm[-1],"first_se_final":fse[-1],"cov_final":cm[-1],"cov_se_final":cse[-1]}
print(f"CONVERGENCE first_reduction={fm[-1]:.3f}±{fse[-1]:.3f} (SE,16 seeds); coverage={cm[-1]:.3f}±{cse[-1]:.3f}")

# ---------- C) Adversary lower bound: pure best-response (eps->0) over longer horizon ----------
def cov_at(eps, steps=24):
    cs=[]
    for sd in (0,1,2):
        s=run(SimConfig(n_agents=8000,steps=steps,seed=sd,adaptive_adversary=True,bandit_epsilon=eps))["summary"]
        d=s["detection_counts_by_role"]["sybil_attacker"]; cs.append(d[0]/max(d[1],1))
    return float(np.mean(cs))
br={e:cov_at(e) for e in (0.0,0.05,0.15)}
R["adversary_floor"]={"static_ref":1.0,"coverage_by_eps_longhorizon":br}
print("ADVERSARY floor (24 steps): eps0.0=%.3f eps0.05=%.3f eps0.15=%.3f"%(br[0.0],br[0.05],br[0.15]))

json.dump(R,open("results/gsa/validation.json","w"),indent=1)
print("SAVED results/gsa/validation.json")