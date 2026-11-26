from multiprocessing import Pool
from datetime import date
import numpy as np, statistics as st, sys
from app.research.wheel.sim import *
M=Mkt(); E=date(2021,12,31); SEEDS=40
B=Spec(rank='rand',capital=100000,n_pos=8,weight=.125)
G=[('BASE (random 8 of top 200, $100k)',{})]
for x in (.10,.16,.20,.30,.40): G.append((f'put delta {x}',dict(delta=x)))
for x in ('1w','2m'): G.append((f'tenor {x}',dict(tenor=x)))
for x in (.10,.15,.20,.40): G.append((f'call delta {x}',dict(call_delta=x)))
G.append(('calls at basis',dict(call_at_basis=True)))
for x in (.5,.75): G.append((f'take profit {int(x*100)}%',dict(profit=x)))
for x in (2.,3.,4.): G.append((f'put stop {x}x',dict(stop=x)))
for x in (50,100,500): G.append((f'top {x} liquid',dict(top_n=x)))
for n,w in ((4,.25),(6,.1667),(12,.0833),(20,.05)): G.append((f'{n} positions',dict(n_pos=n,weight=w)))
for a,b in ((0,.3),(.3,.45),(.45,.6),(.6,.8),(.8,1.2),(1.2,9)): G.append((f'IV band {int(a*100)}-{int(min(b,9)*100)}',dict(iv_lo=a,iv_hi=b)))
G+=[('stock above 200d',dict(trend=True)),('SPY above 200d',dict(spy_up=True)),('both trends',dict(trend=True,spy_up=True))]
for x in (20,25,30,40): G.append((f'no new puts VIX>{x}',dict(vix_hi=x)))
for x in (16,20,25): G.append((f'only new puts VIX>={x}',dict(vix_lo=x)))
G+=[('sell stock below 200d',dict(exit_below_200=True))]
for x in (.1,.2,.3): G.append((f'sell stock -{int(x*100)}%',dict(exit_loss=x)))
G.append(('double costs',dict(spread=.10,tick=.04,comm=1.3,stock_bp=10)))
for c,n,w in ((50000,4,.25),(250000,10,.1)): G.append((f'capital ${c//1000}k, {n} pos',dict(capital=c,n_pos=n,weight=w)))
def one(a):
    k,s=a; r=run(M,replace(B,seed=s,**k),end=E); x=perf(M,r.eq); return x['cagr'],x['dd'],x['sharpe'],r.stats['bankrupt']
if __name__=='__main__':
    y=np.where(np.array([d.year>=2016 and d<=E for d in M.days]),M.spy,np.nan); x=perf(M,y); print(f"SPY {x['cagr']*100:.1f}% DD {x['dd']*100:.0f}% Sh {x['sharpe']:.2f}")
    with Pool(9) as p:
        for nm,k in G:
            o=p.map(one,[(k,s) for s in range(SEEDS)],chunksize=4); c=sorted(v[0] for v in o); d=sorted(v[1] for v in o); h=sorted(v[2] for v in o)
            print(f"{nm:34} median {c[20]*100:5.1f}% [{c[4]*100:5.1f} to {c[35]*100:5.1f}]  DD {d[20]*100:4.0f}%  Sh {h[20]:.2f}  beat SPY {sum(v>x['cagr'] for v in c)}/{SEEDS}",flush=True)
