import sys, random, json
from datetime import date
from multiprocessing import Pool
sys.path.insert(0,'.')
from app.research.system import *
from app.research import yahoo
D=Data(market=yahoo.market(list(CORE),date(2000,5,26),date(2015,12,31)))
C=[Spec(name='A Snap unchanged'),
   Spec(name='B Snap + 1ATR trail',exit_ma=None,trail_atr=1.,max_days=250),
   Spec(name='C 2ATR stop + 1ATR trail',k_stop=2.,exit_ma=None,trail_atr=1.,max_days=250),
   Spec(name='D breadth 3 + delayed trail',k_stop=2.,breadth=3,exit_ma=None,trail_atr=1.,trail_after_r=1.,max_days=250)]
def one(a):
    i,f=a
    return simulate(D,C[i],shifted_signals(D,C[i],f)).total()
if __name__=='__main__':
    random.seed(20001); fr=[random.uniform(.02,.98) for _ in range(2000)]
    with Pool(6) as p:
        for i,sp in enumerate(C):
            r=simulate(D,sp); sims=p.map(one,[(i,f) for f in fr],chunksize=20)
            pct=sum(x<r.total() for x in sims)/20
            y={yy:r.years().get(yy,0) for yy in range(2000,2016)}; pos=sum(v>0 for v in y.values())
            checks=[r.total()>0 and r.sharpe()>=.5,pct>=95,r.max_dd()>-10000,pos>=10]
            print(r.line()); print(f'   random median ${sorted(sims)[1000]/1000:+.1f}k, beats {pct:.1f}% | years+ {pos}/16 | bar {checks} => {"PASS" if all(checks) else "FAIL"}')
            print('   by year',' '.join(f'{k%100:02d}:{v/1000:+.1f}' for k,v in y.items()),flush=True)
    for s in ('QQQ','SPY'):
        c=D.m.c[s]; pk=0;dd=0
        for v in c: pk=max(pk,v);dd=min(dd,v/pk-1)
        yrs=(D.m.dates[-1]-D.m.dates[0]).days/365.25
        print(f'buy & hold {s}: {((c[-1]/c[0])**(1/yrs)-1)*100:.1f}%/yr, worst drop {dd*100:.0f}%')
