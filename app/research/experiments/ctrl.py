import sys, random, json, time
from multiprocessing import Pool
sys.path.insert(0,'.')
from app.research.crazy import *
N=2000
elig={s:[i for i in range(len(B[s])) if IND[s]['s200'][i] is not None and IND[s]['a'][i] is not None and IND[s]['c'][i]>IND[s]['s200'][i] and i<len(B[s])-2] for s in U}
real={s:[snap_entry(s,i) for i in elig[s]] for s in U}
def shifted(frac):
    out={}
    for s in U:
        m=len(elig[s]); o=int(frac*m)
        out[s]={elig[s][(k+o)%m] for k,v in enumerate(real[s]) if v}
    return out
V={'Snap (5-day exit)':dict(),
   'hold 5 days':dict(exit_rule='days5',max_days=60),
   'hold 20 days':dict(exit_rule='days20',max_days=60),
   '3R target':dict(target_r=3,exit_rule='none',max_days=60),
   'trail 1ATR, 3ATR start':dict(trail=1.0,exit_rule='none',max_days=250),
   'trail 1ATR, 2ATR start':dict(k_stop=2.0,trail=1.0,exit_rule='none',max_days=250)}
P=((2016,2026),(2016,2020),(2021,2023),(2024,2026))
def score(T):
    o=[]
    for a,z in P:
        x=[t.pnl for t in T if a<=t.t_out.year<=z]
        o.append(sum(x))
    return o
def one(a):
    name,frac=a
    S=shifted(frac)
    return score(engine(lambda s,i: i in S[s],**V[name]))
if __name__=='__main__':
    t0=time.time(); random.seed(20261120)
    fr=[random.uniform(0.02,0.98) for _ in range(N)]
    res={}
    with Pool(6) as pool:
        for name in V:
            S={s:{elig[s][k] for k,v in enumerate(real[s]) if v} for s in U}
            r=score(engine(lambda s,i: i in S[s],**V[name]))
            sims=pool.map(one,[(name,f) for f in fr],chunksize=25)
            pct=[sum(x[j]<r[j] for x in sims)/N*100 for j in range(4)]
            med=sorted(x[0] for x in sims)[N//2]
            ok=pct[0]>=99 and all(p>=90 for p in pct[1:])
            res[name]=dict(real=r,pct=pct,random_median=med,ok=ok)
            print(f"{name:26} real ${r[0]/1000:+6.1f}k random median ${med/1000:+6.1f}k | beats random: all {pct[0]:5.1f}% 16-20 {pct[1]:5.1f}% 21-23 {pct[2]:5.1f}% 24-26 {pct[3]:5.1f}% | {'CONVINCING' if ok else 'not convincing'} [{time.time()-t0:.0f}s]",flush=True)
    json.dump(res,open('app/research/experiments/ctrl.json','w'))
