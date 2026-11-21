import sys
from datetime import date
sys.path.insert(0,'.')
from app.research.system import *
from app.research.daily import sma
from app.research import yahoo
D=Data(market=yahoo.market(list(CORE),date(2000,5,26),date(2026,10,30)))
vx={b.t.date():b.c for b in yahoo.daily('%5EVIX')}
dates=D.m.dates; V=[]; last=20
for d in dates: last=vx.get(d,last); V.append(last)
V20=sma(V,20)
ERAS=((2001,2008),(2009,2015),(2016,2020),(2021,2026))
def row(name,r):
    y=r.years(); y={k:v for k,v in y.items() if k>=2001}; pos=sum(v>0 for v in y.values()); dd=r.max_dd()
    print(f"{name[:46]:46} n={len(r.trades):4} win {r.win*100:3.0f}% PF {r.pf:4.2f} ${r.total()/1000:+6.1f}k DD ${dd/1000:+6.1f}k Sh {r.sharpe():.2f} yrs {pos}/{len(y)} | eras "+' '.join(f'{r.sharpe(a,z):5.2f}' for a,z in ERAS))
def filt(sp,fn):
    s=D.signals(sp); return {u:[v and fn(u,i) for i,v in enumerate(x)] for u,x in s.items()}
B0=Spec(name='Snap'); T1=Spec(name='trail',exit_ma=None,trail_atr=1.,max_days=250)
for base,nm in ((B0,'Snap'),(T1,'Snap+trail')):
    print('==',nm); row('baseline',simulate(D,base))
    for th in (15,20,25,30): row(f'VIX > {th}',simulate(D,base,filt(base,lambda u,i:V[i]>th)))
    for th in (15,20): row(f'VIX < {th}',simulate(D,base,filt(base,lambda u,i:V[i]<th)))
    row('VIX above its 20d avg',simulate(D,base,filt(base,lambda u,i:V20[i] is not None and V[i]>V20[i])))
    row('VIX >10% above 20d avg',simulate(D,base,filt(base,lambda u,i:V20[i] is not None and V[i]>V20[i]*1.1)))
    row('VIX >20% above 20d avg',simulate(D,base,filt(base,lambda u,i:V20[i] is not None and V[i]>V20[i]*1.2)))
    ma={u:(sma(D.m.c[u],50),D.ind[u]['s200']) for u in CORE}
    row('50d above 200d',simulate(D,base,filt(base,lambda u,i:ma[u][0][i] is not None and ma[u][1][i] is not None and ma[u][0][i]>ma[u][1][i])))
    for b in (2,3,4): row(f'breadth {b}+',simulate(D,replace(base,breadth=b)))
    row('any trend',simulate(D,replace(base,trend='any')))
print('== exits, Snap entry, whole period')
for nm,kw in (('half@1R+trail1',dict(exit_ma=None,partial_r=1.,trail_atr=1.,max_days=250)),('half@1R+trail2',dict(exit_ma=None,partial_r=1.,trail_atr=2.,max_days=250)),
 ('half@.5R+ma5',dict(partial_r=.5)),('half@1R+ma5',dict(partial_r=1.)),('BE1R+ma5',dict(be_after_r=1.)),('target1',dict(exit_ma=None,target_r=1.,max_days=60)),('target2',dict(exit_ma=None,target_r=2.,max_days=60)),('target3',dict(exit_ma=None,target_r=3.,max_days=60)),
 ('tight 1ATR stop + target2',dict(k_stop=1.,exit_ma=None,target_r=2.,max_days=20)),('tight 1ATR stop + target3',dict(k_stop=1.,exit_ma=None,target_r=3.,max_days=20)),('tight 1.5ATR + target3',dict(k_stop=1.5,exit_ma=None,target_r=3.,max_days=20)),('0.5% risk, 1ATR stop, target 4R',dict(risk=.005,k_stop=1.,exit_ma=None,target_r=4.,max_days=30)),('ma3 exit',dict(exit_ma=3)),('ma10 exit',dict(exit_ma=10))):
    row(nm,simulate(D,Spec(name=nm,**kw)))
