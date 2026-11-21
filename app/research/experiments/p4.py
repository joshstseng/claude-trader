import sys, random
from multiprocessing import Pool
sys.path.insert(0,'.')
from longmkt import *
import app.research.portfolio as PF
from app.research.portfolio import run
m=build(fee=0.0165)
ER=((2001,2008),(2009,2015),(2016,2020),(2021,2026))
def tf(u,n=200):
    c=m.c[u]; s=sma(c,n); return [s[k] is not None and c[k]>s[k] for k in range(len(c))]
def F(vt=20,tr=1.5,k=3.): return {u:wants(m,u,vt=vt,trail=tr,k=k) for u in U}
def P(w,add=.25,n=200,c='QQQ'):
    fl=tf(c,n)
    def d(k,h):
        x={c:1.} if fl[k] else {}
        for u in U:
            if w[u][k]: x[L2[u]]=x.get(L2[u],0)+add
        return x
    return d
def Q(w,add=.25): return lambda k,h:{L2[u]:add for u in U if w[u][k]}
def show(r):
    print(f"{r.name[:44]:44} CAGR {r.cagr(2001,2026)*100:5.1f}% DD {r.max_dd()*100:4.0f}% Sh {r.sharpe():.2f} | "+' '.join(f'{r.cagr(a,z)*100:5.1f}' for a,z in ER))
def roll(r,b,yrs=5):
    d=r.dates; e=r.equity; be=b.equity; out=[]; st=next(i for i,x in enumerate(d) if x.year>=2001); h=int(252*yrs)
    for i in range(st,len(d)-h,21): out.append((e[i+h]/e[i])>(be[i+h]/be[i]))
    return sum(out)/len(out)*100,len(out)
def shift(w,f):
    o={}
    for u in U:
        n=len(w[u]); s=int(f*n); o[u]=[w[u][(i-s)%n] for i in range(n)]
    return o
BW=F()
def rnd(a):
    kind,f=a; x=shift(BW,f)
    r=run('',m,P(x) if kind=='P' else Q(x),idle='CASH'); return r.cagr(2001,2026)
if __name__=='__main__':
    q=run('Buy & hold QQQ',m,lambda k,h:{'QQQ':1.}); s=run('Buy & hold SPY',m,lambda k,h:{'SPY':1.}); show(q); show(s)
    base=run('P: Trend QQQ + F adds 25% in 2x',m,P(BW),idle='CASH'); qq=run('Q: F alone, 25% in 2x',m,Q(BW),idle='CASH'); show(base); show(qq)
    print('-- neighbours (P)')
    for vt in (15,18,22,25): show(run(f'VIX>{vt}',m,P(F(vt=vt)),idle='CASH'))
    for tr in (1.,1.25,1.75,2.,3.): show(run(f'trail {tr}',m,P(F(tr=tr)),idle='CASH'))
    for k in (2.,4.): show(run(f'start stop {k}',m,P(F(k=k)),idle='CASH'))
    for add in (.1,.15,.2,.3): show(run(f'adds {add:.0%}',m,P(BW,add),idle='CASH'))
    for n in (100,150,250): show(run(f'trend {n}d',m,P(BW,n=n),idle='CASH'))
    show(run('core SPY instead',m,P(BW,c='SPY'),idle='CASH'))
    print('-- costs (P)')
    PF.SLIP=.0005; show(run('5bp slippage',m,P(BW),idle='CASH')); PF.SLIP=.001; show(run('10bp slippage',m,P(BW),idle='CASH')); PF.SLIP=.0001
    show(run('margin 10%',m,P(BW),idle='CASH',margin_rate=.10))
    print('-- rolling 5-year windows beating buy & hold (%)')
    for nm,r in (('P',base),('Q',qq)): print(nm,'vs QQQ',round(roll(r,q)[0]),'% vs SPY',round(roll(r,s)[0]),'% of',roll(r,q)[1],'windows')
    random.seed(7); fr=[random.uniform(.02,.98) for _ in range(500)]
    with Pool(6) as p:
        for kind,r in (('P',base),('Q',qq)):
            x=sorted(p.map(rnd,[(kind,f) for f in fr],chunksize=10)); real=r.cagr(2001,2026)
            print(f'random timing {kind}: real {real*100:.1f}% random median {x[250]*100:.1f}% 95th {x[475]*100:.1f}% beats {sum(v<real for v in x)/5:.1f}%')
