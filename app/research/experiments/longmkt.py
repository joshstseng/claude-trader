import sys
from datetime import date
from types import SimpleNamespace
sys.path.insert(0,'.')
from app.research.data import D as Bar
from app.research.daily import sma, rsi, atr
from app.research import yahoo
U=['QQQ','SPY','IWM','DIA']; L2={'QQQ':'Q2','SPY':'S2','IWM':'I2','DIA':'D2'}
def build(start=date(2000,5,26),end=date(2026,10,30),lev=2.0,fee=0.0095):
    m=yahoo.market(U,start,end); irx={b.t.date():b.c for b in yahoo.daily('%5EIRX')}; vx={b.t.date():b.c for b in yahoo.daily('%5EVIX')}
    r=[];last=3.0;V=[];lv=20.0
    for d in m.dates:
        last=irx.get(d,last); r.append(max(last,0)/100); lv=vx.get(d,lv); V.append(lv)
    cash=[100.0]
    for k in range(1,len(m.dates)): cash.append(cash[-1]*(1+r[k-1]*(m.dates[k]-m.dates[k-1]).days/365))
    m.bars['CASH']=[Bar(m.bars['SPY'][k].t,c,c,c,c) for k,c in enumerate(cash)]; m.c['CASH']=cash
    for u,n in L2.items():
        b=m.bars[u]; P=100.0; out=[Bar(b[0].t,P,P,P,P)]
        for k in range(1,len(b)):
            pc=b[k-1].c; carry=((lev-1)*r[k-1]+fee)*(m.dates[k]-m.dates[k-1]).days/365
            f=lambda x: max(P*(1+lev*(x/pc-1)-carry),P*.01)
            bar=Bar(b[k].t,f(b[k].o),f(b[k].h),f(b[k].l),f(b[k].c)); out.append(bar); P=bar.c
        m.bars[n]=out; m.c[n]=[x.c for x in out]
    m.vix=V
    return m
def wants(m,u,vt=0,trend='up',exit_='ma5',k=3.0,trail=None):
    b,c=m.bars[u],m.c[u]; rr,tr,ex,a=rsi(c,2),sma(c,200),sma(c,5),atr(b); want=[False]*len(b); i=0
    while i<len(b)-1:
        ib=(c[i]-b[i].l)/(b[i].h-b[i].l) if b[i].h>b[i].l else .5
        ok=tr[i] is not None and a[i] is not None and rr[i] is not None and m.vix[i]>vt and (trend=='any' or c[i]>tr[i]) and (rr[i]<10 or ib<.1)
        if not ok: i+=1; continue
        want[i]=True; j=i+1; stop=b[j].o-k*a[i]; best=b[j].o
        while j<len(b)-1:
            if b[j].l<=stop: break
            if trail:
                best=max(best,b[j].h); stop=max(stop,best-trail*a[j])
                if j-i>=250: break
            elif c[j]>ex[j] or j-i>=20: break
            want[j]=True; j+=1
        i=j if j>i else i+1
    return want
