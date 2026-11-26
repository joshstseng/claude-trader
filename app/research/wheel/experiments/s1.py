import numpy as np
from multiprocessing import Pool
from app.research.wheel.sim import *
M=Mkt(); SC=float(open('data/bars/lab/wheel/scale.txt').read())
B=Spec(rank='rand',capital=100000,n_pos=8,weight=.125,iv_scale=SC,top_n=100)
G=[('Classic, top 100',{})]
for x in (.10,.15,.20): G.append((f'call delta {x}',dict(call_delta=x)))
G+=[('calls at basis',dict(call_at_basis=True)),('calls at basis + .15',dict(call_at_basis=True,call_delta=.15))]
G+=[('no calls ever (delta .01)',dict(call_delta=.01))]
for x in (2.,3.): G.append((f'put stop {x}x',dict(stop=x)))
G+=[('top 25',dict(top_n=25)),('top 50',dict(top_n=50))]
G+=[('IV 20-60',dict(iv_lo=.2,iv_hi=.6)),('IV 30-70',dict(iv_lo=.3,iv_hi=.7)),('IV under 50',dict(iv_hi=.5))]
G+=[('within 10% of 1y high',dict(off_high=.10)),('within 20%',dict(off_high=.20)),('within 30%',dict(off_high=.30))]
G+=[('tenor 2m',dict(tenor='2m')),('delta .35',dict(delta=.35)),('delta .16',dict(delta=.16))]
Q=dict(top_n=50,iv_hi=.6,off_high=.25,call_at_basis=True,call_delta=.20)
G+=[('QUALITY: top50, IV<60, near high, call>=basis .20',Q),('QUALITY + stop 3x',dict(Q,stop=3.)),('QUALITY + 2m',dict(Q,tenor='2m')),('QUALITY delta .35',dict(Q,delta=.35)),('QUALITY delta .16',dict(Q,delta=.16))]
G+=[('QUALITY + QQQ trend core',dict(Q,core='QQQ',core_trend=True)),('QUALITY + QQQ core always',dict(Q,core='QQQ')),('QUALITY + SPY core always',dict(Q,core='SPY'))]
def one(a):
    k,s=a; r=run(M,replace(B,seed=s,**k)); return [perf(M,r.eq,*w) for w in ((2016,2026),(2016,2021),(2022,2026))],r.stats['bankrupt']
if __name__=='__main__':
    print('SPY ALL 14.8% -34% 0.74 | 16-21 17.6% | 22-26 11.4%     QQQ ALL 19.4% -35% 0.81 | 25.0 | 12.6')
    with Pool(9) as p:
        for nm,k in G:
            o=p.map(one,[(k,s) for s in range(40)],chunksize=4); print(f"{nm:48}"+' | '.join(f"{l} {np.median([v[0][i]['cagr'] for v in o])*100:5.1f}% {np.median([v[0][i]['dd'] for v in o])*100:4.0f}% {np.median([v[0][i]['sharpe'] for v in o]):.2f}" for i,l in enumerate(('ALL','16-21','22-26'))),flush=True)
