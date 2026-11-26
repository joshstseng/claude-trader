import numpy as np, pandas as pd
from multiprocessing import Pool
from datetime import date
from app.research.wheel.sim import *
M=Mkt(); P=M.P; C=P.C; R_=pd.DataFrame(C).pct_change(fill_method=None); W=R_.rolling(252,min_periods=120).min().values
SC=float(open('data/bars/lab/wheel/scale.txt').read())
def pick(y,N=12):
    q=max(i for i,d in enumerate(M.days) if d<=date(y-1,11,30)); mo=M.mo[q]; out=[]
    for j in P.rank.get(mo,[])[:100]:
        if P.fail.get(j,10**9)<=q or np.isnan(C[q,j]) or np.isnan(M.s200[q,j]) or np.isnan(W[q,j]): continue
        if .2<=M.rv60[q,j]<=.6 and C[q,j]>=.75*M.hi[q,j] and W[q,j]>-.2 and C[q,j]>M.s200[q,j]: out.append(j)
        if len(out)==N: break
    return out
ALLOW={y:set(pick(y)) for y in range(2017,2027)}
Q=Spec(rank='liq',capital=100000,n_pos=8,weight=.125,iv_scale=SC,top_n=500,call_at_basis=True,call_delta=.2,delta=.25)
r=run(M,Q,start=date(2017,1,3),allow=ALLOW); r2=run(M,replace(Q,spread=.10,tick=.04,comm=1.3,stock_bp=10),start=date(2017,1,3),allow=ALLOW)
print('lists:'); [print(y,' '.join(P.names[j] for j in sorted(v,key=lambda x:P.names.index(P.names[x])))) for y,v in ALLOW.items()]
# equal-weight buy and hold of the same list each year
I=[i for i,d in enumerate(M.days) if d.year>=2017]; eh=[1.]; 
for i in I[1:]:
    v=[C[i,j]/C[i-1,j]-1 for j in ALLOW[M.days[i].year] if not np.isnan(C[i,j]) and not np.isnan(C[i-1,j])]; eh.append(eh[-1]*(1+(np.mean(v) if v else 0)))
H=np.full(M.n,np.nan); H[I]=eh; S=np.full(M.n,np.nan); S[I]=M.spy[I]; Qq=np.full(M.n,np.nan); Qq[I]=M.qqq[I]
for nm,e in (('Watchlist wheel',r.eq),('Watchlist wheel, double costs',r2.eq),('Same stocks, buy & hold',H),('SPY',S),('QQQ',Qq)):
    a=perf(M,e); print(f"{nm:30} {a['cagr']*100:5.1f}%/yr DD {a['dd']*100:4.0f}% Sh {a['sharpe']:.2f} | "+' '.join(f"{y%100}:{perf(M,e,y,y)['cagr']*100:+.0f}" for y in range(2017,2027)))
print(r.stats); print('years beat SPY',sum(perf(M,r.eq,y,y)['cagr']>perf(M,S,y,y)['cagr'] for y in range(2017,2027)),'/10')
