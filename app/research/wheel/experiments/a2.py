from datetime import date
import math, random
from app.research.wheel.indexes import *
from app.research.daily import sma
C=cboe('PUT'); Y=yh('%5EPUT',date(1990,1,1)); f=C[date(2007,1,3)]/Y[date(2007,1,3)]
PUT={**{d:v*f for d,v in Y.items() if d<date(2007,1,3)},**{d:v for d,v in C.items() if d>=date(2007,1,3)}}
TR=yh('%5ESP500TR'); V=yh('%5EVIX'); I=yh('%5EIRX'); SPX=yh('%5EGSPC',date(1985,1,1))
allD=sorted(set(SPX)&set(V)); s200=dict(zip(sorted(SPX),sma([SPX[d] for d in sorted(SPX)],200)))
days=[d for d in sorted(set(PUT)&set(TR)&set(V)&set(SPX)) if d>=date(1996,8,2)]
n=len(days); p=[PUT[d] for d in days]; t=[TR[d] for d in days]; v=[V[d] for d in days]; c=[SPX[d] for d in days]; m=[s200[d] for d in days]
rf=[];l=5.
for d in days: l=I.get(d,l); rf.append(max(l,0)/100/252)
COST=.001
def sim(on, asset=p):
    eq=[1.];prev=False;sw=0
    for i in range(n-1):
        x=on(i); g=asset[i+1]/asset[i]-1 if x else rf[i]
        e=eq[-1]*(1+g)
        if x!=prev: e*=1-COST; sw+=1
        prev=x; eq.append(e)
    return eq,sw
def st(eq,a,b):
    ix=[i for i,d in enumerate(days) if a<=d<=b]; e=[eq[i] for i in ix]; yrs=(days[ix[-1]]-days[ix[0]]).days/365.25
    r=[e[j+1]/e[j]-1-rf[ix[j]] for j in range(len(e)-1)]; mu=sum(r)/len(r); sd=(sum((q-mu)**2 for q in r)/len(r))**.5; pk=e[0];dd=0
    for q in e: pk=max(pk,q);dd=min(dd,q/pk-1)
    return (e[-1]/e[0])**(1/yrs)-1,dd,mu/sd*252**.5
P1=(date(1996,8,2),date(2015,12,31)); P2=(date(2016,1,4),date(2026,10,30)); A=(date(1996,8,2),date(2026,10,30))
def show(nm,on,asset=p):
    eq,sw=sim(on,asset); a=st(eq,*A); b=st(eq,*P1); d=st(eq,*P2)
    print(f"{nm:42} in {sum(on(i) for i in range(n-1))/(n-1)*100:3.0f}% sw/yr {sw/30.2:4.1f} | ALL {a[0]*100:5.1f}% {a[1]*100:4.0f}% {a[2]:.2f} | 96-15 {b[0]*100:5.1f}% {b[1]*100:4.0f}% {b[2]:.2f} | 16-26 {d[0]*100:5.1f}% {d[1]*100:4.0f}% {d[2]:.2f}")
    return eq
show('S&P TR buy & hold',lambda i:True,t); base=show('PUT always',lambda i:True)
print('--- sit out rules on PUT (decide at close, act next day, 10 bp per switch)')
for x in (25,30,35,40,50): show(f'out when VIX > {x}',lambda i,x=x:v[i]<=x)
for x in (12,15,18): show(f'out when VIX < {x}',lambda i,x=x:v[i]>=x)
show('out when S&P < 200-day',lambda i:c[i]>m[i])
show('out when below 200d & VIX 20-30',lambda i:not(c[i]<=m[i] and 20<=v[i]<30))
show('out when below 200d & VIX < 30',lambda i:not(c[i]<=m[i] and v[i]<30))
show('out when below 200d & VIX > 30',lambda i:not(c[i]<=m[i] and v[i]>30))
show('only VIX >= 20',lambda i:v[i]>=20)
show('only above 200d & VIX >= 15',lambda i:c[i]>m[i] and v[i]>=15)
print('--- rotate: S&P when calm uptrend, PUT in fear/down')
def rot(asset_on):
    eq=[1.];prev=None
    for i in range(n-1):
        w=asset_on(i); g=(t if w=='S' else p)[i+1]/(t if w=='S' else p)[i]-1 if w!='C' else rf[i]
        e=eq[-1]*(1+g)
        if prev is not None and w!=prev: e*=1-COST
        prev=w; eq.append(e)
    return eq
def rs(nm,fn):
    eq=rot(fn); a=st(eq,*A);b=st(eq,*P1);d=st(eq,*P2); print(f"{nm:42} | ALL {a[0]*100:5.1f}% {a[1]*100:4.0f}% {a[2]:.2f} | 96-15 {b[0]*100:5.1f}% {b[1]*100:4.0f}% {b[2]:.2f} | 16-26 {d[0]*100:5.1f}% {d[1]*100:4.0f}% {d[2]:.2f}")
rs('S&P if up&VIX<20, else PUT',lambda i:'S' if c[i]>m[i] and v[i]<20 else 'P')
rs('S&P if up, else PUT',lambda i:'S' if c[i]>m[i] else 'P')
rs('S&P if up, PUT if VIX>=30 else cash',lambda i:'S' if c[i]>m[i] else ('P' if v[i]>=30 else 'C'))
rs('S&P if up&VIX<20, PUT if up&VIX>=20, cash down',lambda i:('S' if v[i]<20 else 'P') if c[i]>m[i] else 'C')
print('--- crash episodes: peak-to-trough on S&P, return in the window and 12 months after')
for nm,a,b in (('Dot-com',date(2000,3,24),date(2002,10,9)),('GFC',date(2007,10,9),date(2009,3,9)),('2011',date(2011,4,29),date(2011,10,3)),('2015-16',date(2015,5,21),date(2016,2,11)),('Q4 2018',date(2018,9,20),date(2018,12,24)),('COVID',date(2020,2,19),date(2020,3,23)),('2022',date(2022,1,3),date(2022,10,12)),('2025 tariffs',date(2025,2,19),date(2025,4,8))):
    ia=min(range(n),key=lambda i:abs((days[i]-a).days)); ib=min(range(n),key=lambda i:abs((days[i]-b).days)); ic=min(n-1,ib+252)
    print(f"{nm:13} S&P {t[ib]/t[ia]*100-100:6.1f}% PUT {p[ib]/p[ia]*100-100:6.1f}% | next 12m S&P {t[ic]/t[ib]*100-100:6.1f}% PUT {p[ic]/p[ib]*100-100:6.1f}%")
