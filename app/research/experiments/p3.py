import sys
sys.path.insert(0,'.')
from longmkt import *
from app.research.portfolio import run
m=build(fee=0.0165)
ER=((2001,2008),(2009,2015),(2016,2020),(2021,2026))
def show(r):
    wst=r.max_dd(); print(f"{r.name[:50]:50} CAGR {r.cagr(2001,2026)*100:5.1f}% maxDD {wst*100:4.0f}% Sh {r.sharpe():.2f} ret/DD {r.cagr(2001,2026)/-wst:.2f} | "+' '.join(f'{r.cagr(a,z)*100:5.1f}' for a,z in ER)+f' | expo {r.exposure:.2f}')
def tf(u,n=200):
    c=m.c[u]; s=sma(c,n); return [s[k] is not None and c[k]>s[k] for k in range(len(c))]
W={'A':{u:wants(m,u) for u in U},'E':{u:wants(m,u,vt=15,trend='any') for u in U},'F':{u:wants(m,u,vt=20,exit_='trail',trail=1.5) for u in U}}
tq,ts=tf('QQQ'),tf('SPY')
def dip(w,per,lev=False):
    return lambda k,h:{(L2[u] if lev else u):per for u in U if w[u][k]}
def core(flag,c,w,add,lev=False):
    def d(k,h):
        x={c:1.0} if flag is None or flag[k] else {}
        for u in U:
            if w[u][k]:
                key=L2[u] if lev else u; x[key]=x.get(key,0)+add
        return x
    return d
R=[]
R.append(run('Buy & hold SPY',m,lambda k,h:{'SPY':1.}))
R.append(run('Buy & hold QQQ',m,lambda k,h:{'QQQ':1.}))
R.append(run('Trend SPY (200d) else T-bills',m,lambda k,h:{'SPY':1.} if ts[k] else {},idle='CASH'))
R.append(run('Trend QQQ (200d) else T-bills',m,lambda k,h:{'QQQ':1.} if tq[k] else {},idle='CASH'))
for nm in 'AEF':
    R.append(run(f'{nm} alone, 25%/pos, T-bills',m,dip(W[nm],.25),idle='CASH'))
    R.append(run(f'{nm} alone, 50%/pos, T-bills',m,dip(W[nm],.5),idle='CASH'))
    R.append(run(f'{nm} alone, 25%/pos in 2x, T-bills',m,dip(W[nm],.25,True),idle='CASH'))
for cname,flag,c in (('Trend SPY',ts,'SPY'),('Trend QQQ',tq,'QQQ'),('Always SPY',None,'SPY'),('Always QQQ',None,'QQQ')):
    for nm in 'AEF':
        for add,lev in ((.25,False),(.25,True)):
            R.append(run(f'{cname} + {nm} adds {add:.0%}{" in 2x" if lev else ""}',m,core(flag,c,W[nm],add,lev),idle='CASH' if flag else None))
for r in R: show(r)
