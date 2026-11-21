import sys, random
from datetime import date
from multiprocessing import Pool
sys.path.insert(0,'.')
from app.research.system import *
from app.research import yahoo
H=['XLK','XLF','XLV','XLY','XLP','XLI','XLU','XLB','XLE','MDY','EFA','EWJ','EWG','EWU','EWC']
vx={b.t.date():b.c for b in yahoo.daily('%5EVIX')}
DS={}
for s in H:
    d=Data(syms=(s,),market=yahoo.market([s],date(2001,8,17),date(2015,12,31))); last=20; V=[]
    for x in d.m.dates: last=vx.get(x,last); V.append(last)
    DS[s]=(d,V)
C={'A Snap (control)':(dict(),0),'E Fear dips (VIX>15, no trend)':(dict(trend='any'),15),'F VIX>20 + trend + 1.5ATR trail':(dict(exit_ma=None,trail_atr=1.5,max_days=250),20)}
def run(name,frac=None):
    kw,vt=C[name]; out={}
    for s,(d,V) in DS.items():
        sp=Spec(name=name,universe=(s,),**kw)
        base=d.signals(sp) if frac is None else shifted_signals(d,sp,frac)
        sig={s:[v and V[i]>vt for i,v in enumerate(base[s])]}
        out[s]=simulate(d,sp,sig)
    return out
def tot(a): return sum(run(a[0],a[1])[s].total() for s in H)
if __name__=='__main__':
    random.seed(15); fr=[random.uniform(.02,.98) for _ in range(1000)]
    pfA=None
    with Pool(6) as p:
        for name in C:
            R=run(name); w=sum(t[3] for r in R.values() for t in r.trades if t[3]>0); l=-sum(t[3] for r in R.values() for t in r.trades if t[3]<=0); pf=w/l
            if pfA is None: pfA=pf
            T=sum(r.total() for r in R.values()); n=sum(len(r.trades) for r in R.values()); prof=sum(r.total()>0 for r in R.values())
            sims=p.map(tot,[(name,f) for f in fr],chunksize=10); pct=sum(x<T for x in sims)/10
            checks=[pf>=1.3,prof>=11,pct>=95]+([pf>pfA] if not name.startswith('A') else [])
            print(f'{name:34} n={n} PF {pf:.2f} ${T/1000:+.1f}k profitable {prof}/15 | random median ${sorted(sims)[500]/1000:+.1f}k beats {pct:.1f}% | {checks} => {"PASS" if all(checks) else "FAIL"}')
            print('   ',' '.join(f'{s}:{r.total()/1000:+.1f}' for s,r in R.items()),flush=True)
