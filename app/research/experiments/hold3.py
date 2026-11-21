import sys, random
from datetime import date
from multiprocessing import Pool
sys.path.insert(0,'.')
import longmkt as L
from longmkt import *
import app.research.portfolio as PF
from app.research.portfolio import run
from app.research import yahoo
MAP={'%5ENDX':'QQQ','%5EGSPC':'SPY','%5ERUT':'IWM'}; UU=list(MAP.values()); PF.SLIP=.0005
m0=yahoo.market(list(MAP),date(1990,1,2),date(2000,5,25))
m=SimpleNamespace(dates=m0.dates,bars={MAP[k]:v for k,v in m0.bars.items()},c={MAP[k]:v for k,v in m0.c.items()})
irx={b.t.date():b.c for b in yahoo.daily('%5EIRX')}; vx={b.t.date():b.c for b in yahoo.daily('%5EVIX')}
r=[];last=8.;V=[];lv=20.
for d in m.dates:
    last=irx.get(d,last); r.append(max(last,0)/100); lv=vx.get(d,lv); V.append(lv)
cash=[100.]
for k in range(1,len(m.dates)): cash.append(cash[-1]*(1+r[k-1]*(m.dates[k]-m.dates[k-1]).days/365))
m.bars['CASH']=[Bar(m.bars['SPY'][k].t,c,c,c,c) for k,c in enumerate(cash)]; m.c['CASH']=cash; m.vix=V
for u in UU:
    n=L2[u]; b=m.bars[u]; P=100.; out=[Bar(b[0].t,P,P,P,P)]
    for k in range(1,len(b)):
        pc=b[k-1].c; carry=(r[k-1]+.0165)*(m.dates[k]-m.dates[k-1]).days/365
        f=lambda x:max(P*(1+2*(x/pc-1)-carry),P*.01)
        z=Bar(b[k].t,f(b[k].o),f(b[k].h),f(b[k].l),f(b[k].c)); out.append(z); P=z.c
    m.bars[n]=out; m.c[n]=[x.c for x in out]
W={u:wants(m,u,vt=20,trail=1.5) for u in UU}
s200=sma(m.c['QQQ'],200); fl=[s200[k] is not None and m.c['QQQ'][k]>s200[k] for k in range(len(m.dates))]
def Q(w): return lambda k,h:{L2[u]:.25 for u in UU if w[u][k]}
def Bal(w):
    def d(k,h):
        x={'QQQ':1.} if fl[k] else {}
        for u in UU:
            if w[u][k]: x[L2[u]]=x.get(L2[u],0)+.15
        return x
    return d
def sh(w,f):
    return {u:[w[u][(i-int(f*len(w[u])))%len(w[u])] for i in range(len(w[u]))] for u in UU}
def rn(a):
    k,f=a; x=sh(W,f); return run('',m,Q(x) if k=='Q' else Bal(x),idle='CASH').cagr()
if __name__=='__main__':
    print('signal days',{u:sum(W[u]) for u in UU},'dates',m.dates[0],m.dates[-1])
    random.seed(90); fr=[random.uniform(.02,.98) for _ in range(500)]
    for nm,sy in (('Nasdaq-100','QQQ'),('S&P 500','SPY')):
        x=run(nm,m,lambda k,h:{sy:1.}); print(f'Buy & hold {nm}: {x.cagr()*100:.1f}%/yr DD {x.max_dd()*100:.0f}% Sharpe {x.sharpe():.2f}')
    with Pool(6) as p:
        for k,nm,dec in (('Q','Defensive',Q(W)),('B','Balanced',Bal(W))):
            x=run(nm,m,dec,idle='CASH'); sims=sorted(p.map(rn,[(k,f) for f in fr],chunksize=10)); pct=sum(v<x.cagr() for v in sims)/5
            c=[x.cagr()>0 and x.sharpe()>=.5,x.max_dd()>-.35,pct>=95]
            print(f'{nm}: {x.cagr()*100:.1f}%/yr DD {x.max_dd()*100:.0f}% Sharpe {x.sharpe():.2f} trades {x.trades} | random median {sims[250]*100:.1f}% beats {pct:.1f}% | {c} => {"PASS" if all(c) else "FAIL"}')
