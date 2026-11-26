from multiprocessing import Pool
from datetime import date
import random, numpy as np
from app.research.wheel.sim import *
M=Mkt(); S=40
B=Spec(rank='rand',capital=100000,n_pos=8,weight=.125)
F=dict(vix_lo=20,top_n=100,call_delta=.15)
C={'W1 Classic':{}, 'W2 Fear':F, 'W3 QQQ trend+Fear':dict(F,core='QQQ',core_trend=True), 'W4 SPY trend+Fear':dict(F,core='SPY',core_trend=True),
   'Ctrl QQQ trend':dict(vix_lo=999,core='QQQ',core_trend=True), 'Ctrl SPY trend':dict(vix_lo=999,core='SPY',core_trend=True)}
PER=(('ALL',2016,2026),('DEV 16-21',2016,2021),('HOLDOUT 22-26',2022,2026))
def one(a):
    k,s=a; r=run(M,replace(B,seed=s,**k)); out={n:perf(M,r.eq,x,y) for n,x,y in PER}; ye={}
    for y in range(2016,2027): ye[y]=perf(M,r.eq,y,y)['cagr']
    return out,ye,r.stats
def med(o,n,f): return float(np.median([x[0][n][f] for x in o]))
def shift(a):
    k,fr,s=a; q=np.array(M.vix)>=20; m=np.roll(q,int(fr*M.n)); r=run(M,replace(B,seed=s,**{**k,'vix_lo':0}),mask=m); return perf(M,r.eq)['sharpe'],perf(M,r.eq)['cagr']
if __name__=='__main__':
    bench={}
    for nm,a in (('SPY',M.spy),('QQQ',M.qqq)):
        A=np.where(np.array([d.year>=2016 for d in M.days]),a,np.nan); bench[nm]={n:perf(M,A,x,y) for n,x,y in PER}; bench[nm+'_y']={y:perf(M,A,y,y)['cagr'] for y in range(2016,2027)}
        print(nm,' | '.join(f"{n} {bench[nm][n]['cagr']*100:.1f}% DD {bench[nm][n]['dd']*100:.0f}% Sh {bench[nm][n]['sharpe']:.2f}" for n,_,_ in PER))
    res={}
    with Pool(9) as p:
        for nm,k in C.items():
            o=p.map(one,[(k,s) for s in range(S)],chunksize=4); res[nm]=o
            print(f"\n{nm}: "+' | '.join(f"{n} {med(o,n,'cagr')*100:.1f}% DD {med(o,n,'dd')*100:.0f}% Sh {med(o,n,'sharpe'):.2f}" for n,_,_ in PER))
            ys={y:float(np.median([x[1][y] for x in o])) for y in range(2016,2027)}; print('  years',' '.join(f"{y%100}:{v*100:+.0f}" for y,v in ys.items()),'positive',sum(v>0 for v in ys.values()),'/11')
            print('  portfolios beating SPY: ALL',sum(x[0]['ALL']['cagr']>bench['SPY']['ALL']['cagr'] for x in o),'HOLDOUT',sum(x[0]['HOLDOUT 22-26']['cagr']>bench['SPY']['HOLDOUT 22-26']['cagr'] for x in o),'of',S)
            if 'Ctrl' not in nm:
                dc=p.map(one,[(dict(k,spread=.10,tick=.04,comm=1.3,stock_bp=10),s) for s in range(S)],chunksize=4); print(f"  double costs: ALL {med(dc,'ALL','cagr')*100:.1f}% HOLDOUT {med(dc,'HOLDOUT 22-26','cagr')*100:.1f}%")
            if nm!='W1 Classic' and 'Ctrl' not in nm:
                random.seed(7); fr=[random.uniform(.05,.95) for _ in range(120)]; shf=p.map(shift,[(k,f,s) for f in fr for s in range(3)],chunksize=12); sh=sorted(np.median([v[0] for v in shf[i:i+3]]) for i in range(0,len(shf),3)); real=float(np.median([x[0]['ALL']['sharpe'] for x in o])); print(f"  random VIX timing: real Sharpe {real:.2f} vs random median {sh[60]:.2f}; beats {sum(v<real for v in sh)/len(sh)*100:.0f}%")
