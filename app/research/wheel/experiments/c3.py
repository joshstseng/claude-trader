from multiprocessing import Pool
from datetime import date
import numpy as np, statistics as st, sys
from app.research.wheel.sim import *
M=Mkt(); E=date(2021,12,31); SEEDS=40
B=Spec(rank='rand',capital=100000,n_pos=8,weight=.125)
F=dict(vix_lo=20,top_n=100)
G=[('Classic (all markets)',{}),('Fear only: VIX>=20',F),('Fear VIX>=25',dict(F,vix_lo=25)),('Fear VIX>=18',dict(F,vix_lo=18))]
for x in (.10,.16,.2,.3,.4): G.append((f'Fear, put delta {x}',dict(F,delta=x)))
for x in (.1,.15,.2): G.append((f'Fear, call delta {x}',dict(F,call_delta=x)))
for x in (2.,3.): G.append((f'Fear, stop {x}x',dict(F,stop=x)))
G.append(('Fear, tenor 2m',dict(F,tenor='2m')))
for n,w in ((4,.25),(6,.1667),(12,.0833)): G.append((f'Fear, {n} positions',dict(F,n_pos=n,weight=w)))
G.append(('Fear, stock above 200d',dict(F,trend=True)))
G+=[('Buy SPY only (no puts) check',dict(vix_lo=999,core='SPY'))]
for cr in ('SPY','QQQ'):
    G+=[(f'{cr} core + classic wheel',dict(core=cr)),(f'{cr} core + fear wheel',dict(F,core=cr)),(f'{cr} core + fear, call .15',dict(F,core=cr,call_delta=.15)),(f'{cr} core + fear, stop 3x',dict(F,core=cr,stop=3.)),(f'{cr} core + fear 4 pos',dict(F,core=cr,n_pos=4,weight=.25)),(f'{cr} core + fear 12 pos',dict(F,core=cr,n_pos=12,weight=.0833)),(f'{cr} core(trend) + fear',dict(F,core=cr,core_trend=True)),(f'{cr} core + fear VIX>=25',dict(F,core=cr,vix_lo=25))]
def one(a):
    k,s=a; r=run(M,replace(B,seed=s,**k),end=E); x=perf(M,r.eq); return x['cagr'],x['dd'],x['sharpe'],r.stats['bankrupt']
if __name__=='__main__':
    y=np.where(np.array([d.year>=2016 and d<=E for d in M.days]),M.spy,np.nan); x=perf(M,y); print(f"SPY {x['cagr']*100:.1f}% DD {x['dd']*100:.0f}% Sh {x['sharpe']:.2f}")
    with Pool(9) as p:
        for nm,k in G:
            o=p.map(one,[(k,s) for s in range(SEEDS)],chunksize=4); c=sorted(v[0] for v in o); d=sorted(v[1] for v in o); h=sorted(v[2] for v in o)
            print(f"{nm:34} median {c[20]*100:5.1f}% [{c[4]*100:5.1f} to {c[35]*100:5.1f}]  DD {d[20]*100:4.0f}%  Sh {h[20]:.2f}  beat SPY {sum(v>x['cagr'] for v in c)}/{SEEDS}",flush=True)
