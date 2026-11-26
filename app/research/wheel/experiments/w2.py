import numpy as np, pandas as pd
from multiprocessing import Pool
from datetime import date
from app.research.wheel.sim import *
M=Mkt(); P=M.P; C=P.C; W=pd.DataFrame(C).pct_change(fill_method=None).rolling(252,min_periods=120).min().values
SC=float(open('data/bars/lab/wheel/scale.txt').read())
SAME={'GOOG':'GOOGL','FB':'META','BRK.B':'BRK.A','FOX':'FOXA','NWS':'NWSA','UA':'UAA'}
def pick(y,N=12):
    q=max(i for i,d in enumerate(M.days) if d<=date(y-1,11,30)); mo=M.mo[q]; out=[]; seen=set()
    for j in P.rank.get(mo,[])[:100]:
        nm=SAME.get(P.names[j],P.names[j])
        if nm in seen or P.fail.get(j,10**9)<=q or np.isnan(C[q,j]) or np.isnan(M.s200[q,j]) or np.isnan(W[q,j]): continue
        if .2<=M.rv60[q,j]<=.6 and C[q,j]>=.75*M.hi[q,j] and W[q,j]>-.2 and C[q,j]>M.s200[q,j]: out.append(j); seen.add(nm)
        if len(out)==N: break
    return out
L={N:{y:set(pick(y,N)) for y in range(2017,2027)} for N in (8,10,12,15,20,30)}
Q=Spec(rank='rand',capital=100000,n_pos=8,weight=.125,iv_scale=SC,top_n=500,call_at_basis=True,call_delta=.2)
G=[('WATCHLIST RULE (12 names, 8 positions)',12,{})]
for N in (8,10,15,20,30): G.append((f'list of {N}',N,{}))
for n,w in ((4,.25),(6,.1667),(10,.1)): G.append((f'{n} positions',12,dict(n_pos=n,weight=w)))
for x in (.16,.20,.30,.35): G.append((f'put delta {x}',12,dict(delta=x)))
for x in (.10,.15,.30): G.append((f'call delta {x}',12,dict(call_delta=x)))
G+=[('calls may go below basis',12,dict(call_at_basis=False)),('2-month options',12,dict(tenor='2m')),('weekly options',12,dict(tenor='1w')),('put stop 3x',12,dict(stop=3.)),('take profit 50%',12,dict(profit=.5)),('SPY above 200d only',12,dict(spy_up=True)),('sit out VIX>30',12,dict(vix_hi=30)),('only VIX>=20',12,dict(vix_lo=20)),('double costs',12,dict(spread=.10,tick=.04,comm=1.3,stock_bp=10)),('cash earns 0%',12,dict(idle_yield=0.)),('$50k, 4 positions',12,dict(capital=50000,n_pos=4,weight=.25)),('$250k, 10 positions',12,dict(capital=250000,n_pos=10,weight=.1)),('no IV scale',12,dict(iv_scale=1.))]
def one(a):
    N,k,s=a; r=run(M,replace(Q,seed=s,**k),start=date(2017,1,3),allow=L[N]); return [perf(M,r.eq),perf(M,r.eq,2017,2021),perf(M,r.eq,2022,2026)]
if __name__=='__main__':
    I=[i for i,d in enumerate(M.days) if d.year>=2017]
    def eqm(w):
        e=[1.]
        for i in I[1:]: e.append(e[-1]*(1+w*(M.spy[i]/M.spy[i-1]-1)+(1-w)*M.rf[i-1]/252))
        x=np.full(M.n,np.nan); x[I]=e; return x
    for w in (1.,.8,.7,.6,.5):
        a=perf(M,eqm(w)); print(f"{int(w*100)}% SPY + {100-int(w*100)}% T-bills {a['cagr']*100:5.1f}%/yr DD {a['dd']*100:4.0f}% vol {a['vol']*100:.1f}% Sh {a['sharpe']:.2f} | 22-26 {perf(M,eqm(w),2022,2026)['cagr']*100:.1f}%")
    with Pool(9) as p:
        for nm,N,k in G:
            o=p.map(one,[(N,k,s) for s in range(40)],chunksize=4); c=[v[0]['cagr'] for v in o]; a=lambda i,f:np.median([v[i][f] for v in o])
            print(f"{nm:38} {a(0,'cagr')*100:5.1f}% [{np.percentile(c,10)*100:4.1f}-{np.percentile(c,90)*100:4.1f}] DD {a(0,'dd')*100:4.0f}% vol {a(0,'vol')*100:.1f}% Sh {a(0,'sharpe'):.2f} | 17-21 {a(1,'cagr')*100:5.1f}% | 22-26 {a(2,'cagr')*100:5.1f}% Sh {a(2,'sharpe'):.2f}",flush=True)
