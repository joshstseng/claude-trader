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
def full(s):
    r=run(M,replace(Q,seed=s),start=date(2017,1,3),allow=L[12]); e=r.eq; I=np.where(~np.isnan(e))[0]; avg=float(np.mean(e[I])); yrs=(M.days[I[-1]]-M.days[I[0]]).days/365.25
    w=[t for t in r.trades]; return {y:perf(M,e,y,y)['cagr'] for y in range(2017,2027)},r.stats['premium']/yrs/avg,r.stats['puts']/yrs,r.stats['assigned']/max(1,r.stats['puts']),sum(t[3]>0 for t in w)/max(1,len(w)),(e[I[1:]]/e[I[:-1]]-1),I[1:]
if __name__=='__main__':
    with Pool(9) as p: o=p.map(full,range(40))
    print('year median wheel / SPY / QQQ:',' '.join(f"{y}:{np.median([x[0][y] for x in o])*100:+.1f}/{perf(M,np.where(np.array([d.year==y for d in M.days]),M.spy,np.nan))['cagr']*100:+.1f}/{perf(M,np.where(np.array([d.year==y for d in M.days]),M.qqq,np.nan))['cagr']*100:+.1f}" for y in range(2017,2027)))
    print('premium collected/yr as %% of average account %.1f%%; puts/yr %.0f; assigned %.0f%%; winning trades %.0f%%'%(np.median([x[1] for x in o])*100,np.median([x[2] for x in o]),np.median([x[3] for x in o])*100,np.median([x[4] for x in o])*100))
    R=np.mean([x[5] for x in o],axis=0); I=o[0][6]; sp=M.spy[I]/M.spy[I-1]-1; lab=[]
    for i in I:
        q=i-1; u=M.spy[q]>M.spy200[q]; v=M.vix[q]; lab.append(('Uptrend' if u else 'Downtrend')+(', VIX under 20' if v<20 else ', VIX 20-30' if v<30 else ', VIX 30+'))
    G=pd.DataFrame(dict(w=R,s=sp,l=lab))
    for nm,g in G.groupby('l'): print(f"{nm:28} days {len(g)/len(G)*100:3.0f}% wheel {g.w.mean()*252*100:+6.1f}%/yr SPY {g.s.mean()*252*100:+6.1f}%/yr")
