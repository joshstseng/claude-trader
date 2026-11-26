import numpy as np, pandas as pd, bisect
from datetime import timedelta
from multiprocessing import Pool
from app.research.wheel.sim import *
from app.research.wheel.fetch import DIR
from app.backtest import bumi as BB
M=Mkt(); P=M.P; r=pd.DataFrame(P.C).pct_change(fill_method=None); rv=r.rolling(60,min_periods=30).std().shift(1); v=pd.DataFrame(P.v.astype(float)); av=v.rolling(20,min_periods=10).mean().shift(1)
ev=((r.abs()>=2.5*rv)&(v>=2.5*av)).values
events={j:np.where(ev[:,j])[0] for j in range(P.C.shape[1])}
ord_=np.array([d.toordinal() for d in M.days])
def crosses(j,i,dx):
    x=events[j]; x=x[x<i]
    x=[q for q in x if ord_[i]-ord_[q]<=400]
    if len(x)<2: return np.nan
    # a quarterly event projected forward from the most recent one
    t=ord_[x[-1]]
    while t<ord_[i]: t+=91
    return float(t-7<=dx and t+7>=ord_[i])
D=pd.read_pickle(DIR/'real_puts.pkl'); ix={d:i for i,d in enumerate(M.days)}; pos={s:j for j,s in enumerate(P.names)}
D['cross']=[crosses(pos[u],ix[d],d.toordinal()+int(round(t))) for u,d,t in zip(D.u,D.d,D.dte)]
print('REAL puts 2024-26, using a projected earnings date (no earnings calendar):')
def line(g): return f"n {len(g):5} win {g.win.mean()*100:3.0f}% ret/trade {g.ret.mean()*100:+5.2f}% worst 5% {g.ret.quantile(.05)*100:+5.1f}% premium {g.prem.div(g.K).mean()*100:.2f}% stock {g.stock.mean()*100:+5.2f}%"
for c,l in ((1.,'window likely has earnings'),(0.,'window likely clear')): print(f' {l:30}',line(D[D.cross==c]))
Y=pd.read_pickle(DIR/'model_puts.pkl'); Y['cross']=[crosses(int(j),int(k),ord_[int(k)]+31) for j,k in zip(Y.j,Y.k)]; print('MODEL puts 2016-26 (model has no earnings premium, so losses are overstated for earnings windows):')
for c,l in ((1.,'likely has earnings'),(0.,'likely clear')):
    g=Y[Y.cross==c]; print(f' {l:30} n {len(g):5} ret/trade {g.ret.mean()*100:+5.2f}% worst 5% {g.ret.quantile(.05)*100:+5.1f}% stock {g.stock.mean()*100:+5.2f}%')
# Does the wheel diversify Bumi?
m,bu=BB.run(True); Bq={d:e for d,e in zip(m.dates,bu.equity)}
SC=float(open('data/bars/lab/wheel/scale.txt').read())
Q=Spec(rank='rand',capital=100000,n_pos=8,weight=.125,iv_scale=SC,top_n=50,iv_hi=.6,off_high=.25,call_at_basis=True,call_delta=.2)
def f(s): return run(M,replace(Q,seed=s)).eq
if __name__=='__main__':
    with Pool(9) as p: E=p.map(f,range(40))
    I=[i for i,d in enumerate(M.days) if d.year>=2016 and d in Bq]; W=np.array([np.array([e[i] for i in I]) for e in E]); w=(W[:,1:]/W[:,:-1]-1).mean(axis=0); b=np.array([Bq[M.days[i]] for i in I]); br=b[1:]/b[:-1]-1; sr=M.spy[I][1:]/M.spy[I][:-1]-1; qr=M.qqq[I][1:]/M.qqq[I][:-1]-1
    print('corr wheel/Bumi %.2f, wheel/SPY %.2f, Bumi/SPY %.2f'%(np.corrcoef(w,br)[0,1],np.corrcoef(w,sr)[0,1],np.corrcoef(br,sr)[0,1]))
    def stat(x):
        e=np.cumprod(1+x); y=len(x)/252; return f"{(e[-1]**(1/y)-1)*100:5.1f}%/yr DD {((e/np.maximum.accumulate(e))-1).min()*100:4.0f}% Sh {(x.mean()-np.mean([M.rf[i]/252 for i in I]))/x.std()*252**.5:.2f}"
    for nm,x in (('Quality wheel avg',w),('Bumi',br),('SPY',sr),('QQQ',qr),('75% Bumi + 25% wheel',.75*br+.25*w),('50/50 Bumi + wheel',.5*br+.5*w),('25% Bumi + 75% wheel',.25*br+.75*w)): print(f'{nm:24}',stat(x))
