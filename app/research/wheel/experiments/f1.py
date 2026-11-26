import numpy as np, pandas as pd, math
from app.research.wheel.sim import *
from app.research.wheel.fetch import DIR
M=Mkt(); P=M.P; C=P.C; O=P.O; n=M.n
LC=np.log(np.where(C>0,C,np.nan)); ret=pd.DataFrame(C).pct_change(fill_method=None); spy=pd.Series(M.spy).pct_change()
mom=lambda w:C/np.vstack([np.full((w,C.shape[1]),np.nan),C[:-w]])-1
m12,m6,m1=mom(252),mom(126),mom(21); hi=pd.DataFrame(C).rolling(252,min_periods=120).max().values; worst=ret.rolling(252,min_periods=120).min().values
var=spy.rolling(252,min_periods=120).var(); beta=ret.rolling(252,min_periods=120).cov(spy).div(var,axis=0).values
rows=[]
for k,x in M.cyc['1m'].items():
    if M.days[k].year<2016: continue
    q=k-1; mo=M.mo[q]; pr=M.months[M.months.index(mo)-1]; T=max((M.days[x]-M.days[k]).days,1)/365
    for rk,j in enumerate(P.rank.get(pr,[])[:200]):
        if np.isnan(O[k,j]) or np.isnan(C[q,j]) or P.fail.get(j,10**9)<=q: continue
        S=float(O[k,j]); K,iv=M.strike(j,q,S,T,.25,True)
        if K is None: continue
        fz=P.fail.get(j,10**9); last=M.lastdata[j]
        if fz<=x: Sx=0.
        else:
            i=min(x,last); Sx=float(C[i,j])
            if np.isnan(Sx): continue
        px=bs(S,K,T,M.rf[k],iv,True); prem=px-max(px*.05,.02*S/100)
        rows.append((j,k,M.days[k].year,rk,(prem-max(K-Sx,0))/K,Sx/S-1,prem/K,iv,Sx<K,M.vix[q],M.spy[q]>M.spy200[q],m12[q,j],m6[q,j],m1[q,j],C[q,j]/hi[q,j]-1,M.rv60[q,j],worst[q,j],beta[q,j],C[q,j]>M.s200[q,j] if not np.isnan(M.s200[q,j]) else np.nan))
D=pd.DataFrame(rows,columns='j k y rank ret stock prem iv assigned vix up m12 m6 m1 off_hi rv60 worst beta trend'.split()); D.to_pickle(DIR/'model_puts.pkl')
print('model put trades',len(D),'names',D.j.nunique(),'bankrupt-loss trades',int((D.stock<=-.999).sum()))
dv,ho=D[D.y<=2021],D[D.y>=2022]
def line(g): return f"{len(g):5} {g.ret.mean()*100:+5.2f}% win {(g.ret>0).mean()*100:3.0f}% p5 {g.ret.quantile(.05)*100:+5.0f}% stock {g.stock.mean()*100:+5.2f}%"
print('ALL dev',line(dv),'| holdout',line(ho))
for f in ('iv','rv60','beta','m12','m6','m1','off_hi','worst','rank'):
    print('--',f,'quintiles (low to high): dev | holdout')
    for q in range(5):
        def get(X): 
            r=X.groupby('k')[f].rank(pct=True); return X[(r>q/5)&(r<=(q+1)/5)]
        print(f'  Q{q+1}',line(get(dv.dropna(subset=[f]))),'|',line(get(ho.dropna(subset=[f]))))
for nm,c in (('stock above 200d',lambda X:X.trend==1),('stock below 200d',lambda X:X.trend==0),('SPY up',lambda X:X.up==1),('SPY down',lambda X:X.up==0),('VIX<15',lambda X:X.vix<15),('VIX 15-20',lambda X:(X.vix>=15)&(X.vix<20)),('VIX 20-30',lambda X:(X.vix>=20)&(X.vix<30)),('VIX 30+',lambda X:X.vix>=30)):
    print(f'{nm:18}',line(dv[c(dv)]),'|',line(ho[c(ho)]))
print('by year',' '.join(f"{y%100}:{g.ret.mean()*100:+.2f}/{g.stock.mean()*100:+.2f}" for y,g in D.groupby('y')))
