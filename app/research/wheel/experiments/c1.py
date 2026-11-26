from multiprocessing import Pool
from datetime import date
import numpy as np
from app.research.wheel.sim import *
M=Mkt(); E=date(2021,12,31)
B=Spec()
G=[('BASE',{})]
for x in (.10,.16,.20,.30,.35,.40,.50): G.append((f'put delta {x}',dict(delta=x)))
for x in ('1w','2m'): G.append((f'tenor {x}',dict(tenor=x)))
for x in (.15,.2,.4,.5): G.append((f'call delta {x}',dict(call_delta=x)))
for x in (.25,.5,.75): G.append((f'take profit {int(x*100)}%',dict(profit=x)))
for x in (1.5,2.,3.,4.): G.append((f'put stop {x}x',dict(stop=x)))
for x in (25,50,100,300,500): G.append((f'top {x} liquid',dict(top_n=x)))
for n,w in ((3,.33),(4,.25),(8,.125),(10,.1),(15,.0667)): G.append((f'{n} positions',dict(n_pos=n,weight=w)))
for x in ('iv','iv_low','rand'): G.append((f'rank {x}',dict(rank=x)))
for a,b in ((0,.3),(.3,.45),(.45,.6),(.6,.8),(.8,1.2),(1.2,9)): G.append((f'IV band {int(a*100)}-{int(min(b,9)*100)}',dict(iv_lo=a,iv_hi=b,rank='rand')))
G+=[('stock above 200d',dict(trend=True)),('SPY above 200d',dict(spy_up=True)),('both trend',dict(trend=True,spy_up=True))]
for x in (20,25,30,40): G.append((f'no new puts VIX>{x}',dict(vix_hi=x)))
for x in (14,16,20): G.append((f'no new puts VIX<{x}',dict(vix_lo=x)))
G+=[('sell stock below 200d',dict(exit_below_200=True))]
for x in (.1,.15,.2,.3): G.append((f'sell stock -{int(x*100)}%',dict(exit_loss=x)))
G+=[('calls at cost basis only',dict(call_at_basis=True))]
for x in (.0,.1,.15): G.append((f'spread {int(x*100)}%',dict(spread=x)))
G.append(('double costs',dict(spread=.10,tick=.04,comm=1.3,stock_bp=10)))
for x in (25000,100000,250000): G.append((f'capital ${x//1000}k',dict(capital=x)))
def go(a):
    nm,k=a; r=run(M,replace(B,name=nm,**k),end=E); x=perf(M,r.eq); s=r.stats; return nm,x,s,len(r.trades)
if __name__=='__main__':
    y=np.where(np.array([d.year>=2016 and d<=E for d in M.days]),M.spy,np.nan); q=np.where(np.array([d.year>=2016 and d<=E for d in M.days]),M.qqq,np.nan)
    for n,a in (('SPY',y),('QQQ',q)): x=perf(M,a); print(f"{n:30} {x['cagr']*100:6.1f}%  DD {x['dd']*100:5.0f}%  Sh {x['sharpe']:.2f}")
    with Pool(8) as p:
        for nm,x,s,t in p.imap(go,G):
            print(f"{nm:30} {x['cagr']*100:6.1f}%  DD {x['dd']*100:5.0f}%  Sh {x['sharpe']:.2f} | puts {s['puts']:4} assigned {s['assigned']:3} bankrupt {s['bankrupt']} premium ${s['premium']/1000:5.0f}k",flush=True)
