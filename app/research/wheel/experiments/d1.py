from datetime import date
from collections import defaultdict
import numpy as np, pandas as pd, math
from app.research.wheel.indexes import *
from app.research.wheel.sim import *
C=cboe('PUT'); Y=yh('%5EPUT',date(1990,1,1)); f=C[date(2007,1,3)]/Y[date(2007,1,3)]; PUT={**{d:v*f for d,v in Y.items() if d<date(2007,1,3)},**{d:v for d,v in C.items() if d>=date(2007,1,3)}}
TR=yh('%5ESP500TR'); BX=cboe('BXMD')
days=[d for d in sorted(set(PUT)&set(TR)&set(BX)) if d>=date(1996,8,2)]; me={}
for d in days: me[(d.year,d.month)]=d
ms=sorted(me); R=[]
for a,b in zip(ms,ms[1:]):
    x,y=me[a],me[b]; R.append((b,TR[y]/TR[x]-1,PUT[y]/PUT[x]-1,BX[y]/BX[x]-1))
D=pd.DataFrame(R,columns=['m','spx','put','bx'])
print('MONTHLY, real indexes Aug 1996-2026, n',len(D))
for nm,lo,hi in (('Crash: S&P below -7%',-1,-.07),('Down -7 to -3%',-.07,-.03),('Mild down -3 to 0%',-.03,0),('Flat/up 0 to 2%',0,.02),('Up 2 to 4%',.02,.04),('Strong up 4 to 7%',.04,.07),('Surge above 7%',.07,9)):
    g=D[(D.spx>=lo)&(D.spx<hi)]; print(f"{nm:24} n {len(g):3} S&P {g.spx.mean()*100:+6.2f}%  PUT {g.put.mean()*100:+6.2f}%  edge {(g.put-g.spx).mean()*100:+5.2f}  PUT beat S&P {(g.put>g.spx).mean()*100:3.0f}%")
print('12-month windows (rolling):')
t=(1+D.spx).rolling(12).apply(np.prod,raw=True)-1; p=(1+D.put).rolling(12).apply(np.prod,raw=True)-1; E=pd.DataFrame({'t':t,'p':p}).dropna()
for nm,lo,hi in (('S&P 12m below -10%',-1,-.1),('-10 to 0%',-.1,0),('0 to 10%',0,.1),('10 to 20%',.1,.2),('20 to 30%',.2,.3),('above 30%',.3,9)):
    g=E[(E.t>=lo)&(E.t<hi)]; print(f"  {nm:20} n {len(g):3} S&P {g.t.mean()*100:+6.1f}% PUT {g.p.mean()*100:+6.1f}% PUT wins {(g.p>g.t).mean()*100:3.0f}%")
print('Overall rolling 12m PUT beat S&P %.0f%%'%((E.p>E.t).mean()*100))
# stock wheel P&L decomposition and market attribution
M=Mkt(); B=Spec(rank='rand',capital=100000,n_pos=8,weight=.125)
rows=[]; tt=defaultdict(float); tn=defaultdict(int); prem=[]
for s in range(40):
    r=run(M,replace(B,seed=s)); prem.append(r.stats['premium'])
    for j,t0,k,pnl,why in r.trades: tt[why]+=pnl/40; tn[why]+=1
    e=r.eq; I=np.where(~np.isnan(e))[0]; rows.append(pd.Series(e[I[1:]]/e[I[:-1]]-1,index=I[1:]))
avg=pd.concat(rows,axis=1).mean(axis=1); spyr=pd.Series(M.spy[1:]/M.spy[:-1]-1,index=range(1,M.n))
print('STOCK WHEEL by exit type, $ per run: ',{k:round(v) for k,v in sorted(tt.items(),key=lambda a:a[1])},'count per run',{k:round(v/40) for k,v in tn.items()},'premium collected per run',round(np.mean(prem)))
st=[]
for i in avg.index:
    q=i-1; up=M.spy[q]>M.spy200[q]; v=M.vix[q]; st.append(('Uptrend' if up else 'Downtrend')+(' VIX<20' if v<20 else ' VIX 20-30' if v<30 else ' VIX 30+'))
G=pd.DataFrame({'w':avg,'s':spyr.reindex(avg.index),'st':st})
print('STOCK WHEEL by market state, annualized (2016-2026)')
for nm,g in G.groupby('st'): print(f"  {nm:22} days {len(g)/len(G)*100:3.0f}% wheel {g.w.mean()*252*100:+6.1f}% SPY {g.s.mean()*252*100:+6.1f}%")
