from datetime import date
import statistics as st, math
from app.research.wheel.indexes import *
from app.research.daily import sma
S={k:cboe(k) for k in NAMES}; _y=yh('%5EPUT',date(1990,1,1)); _f=S['PUT'][date(2007,1,3)]/_y[date(2007,1,3)]; S['PUT']={**{d:v*_f for d,v in _y.items() if d<date(2007,1,3)},**{d:v for d,v in S['PUT'].items() if d>=date(2007,1,3)}}; TR=yh('%5ESP500TR'); V=yh('%5EVIX'); I=yh('%5EIRX'); SPX=yh('%5EGSPC',date(1985,1,1))
print({k:(min(v),max(v)) for k,v in S.items()}, 'TR',min(TR),max(TR),'IRX',min(I),'SPX',min(SPX))
days=sorted(set(TR)&set(V)&set(SPX)); days=[d for d in days if d>=date(1990,1,2)]
ir=[];l=5.
for d in days: l=I.get(d,l); ir.append(max(l,0)/100/252)
def row(nm,ser,a=None,b=None):
    D=[d for d in days if d in ser and (a is None or d>=a) and (b is None or d<=b)]
    if len(D)<50: return
    idx={d:i for i,d in enumerate(days)}; x=stats(D,[ser[d] for d in D],[ir[idx[d]] for d in D[:-1]])
    print(f"  {nm:7} {x['cagr']*100:6.2f}%  DD {x['dd']*100:6.1f}%  vol {x['vol']*100:5.1f}%  Sharpe {x['sharpe']:.2f}")
for a,b,lab in ((date(1996,8,2),None,'Aug 1996-2026 (PUT daily)'),(date(2006,2,1),None,'2006-2026 (all indexes)'),(date(1996,8,2),date(2002,12,31),'1996-2002 incl dot-com'),(date(2003,1,2),date(2007,6,29),'2003-Jun 2007'),(date(2007,7,2),date(2015,12,31),'2007-2015'),(date(2016,1,4),date(2021,12,31),'2016-2021'),(date(2022,1,3),None,'2022-2026')):
    print(lab); row('S&P TR',TR,a,b); [row(k,S[k],a,b) for k in S]
# conditional returns by prior-close market state
sm=sma([SPX[d] for d in days],200); c=[SPX[d] for d in days]; v=[V[d] for d in days]
def ret(ser,i): return ser[days[i+1]]/ser[days[i]]-1 if days[i] in ser and days[i+1] in ser else None
def bucket(lab,cond):
    J=[i for i in range(max(200,days.index(next(d for d in days if d>=date(1996,8,2)))),len(days)-1) if cond(i)]
    out=[]
    for nm,ser in (('S&P',TR),('PUT',S['PUT']),('BXMD',S['BXMD'])):
        x=[ret(ser,i) for i in J]; x=[q for q in x if q is not None]; m=st.mean(x); sd=st.pstdev(x); ex=m-st.mean(ir[i] for i in J)
        out.append(f"{nm} {m*252*100:+6.1f}%/yr vol {sd*252**.5*100:4.0f}% Sh {ex/sd*252**.5:5.2f}")
    print(f"{lab:32} {len(J)/(len(days)-201)*100:3.0f}% days | "+' | '.join(out))
print('BY MARKET STATE AT PRIOR CLOSE (Aug 1996-2026)')
bucket('up + VIX<15',lambda i:c[i]>sm[i] and v[i]<15); bucket('up + VIX 15-20',lambda i:c[i]>sm[i] and 15<=v[i]<20); bucket('up + VIX 20-30',lambda i:c[i]>sm[i] and 20<=v[i]<30); bucket('up + VIX 30+',lambda i:c[i]>sm[i] and v[i]>=30)
bucket('down + VIX<20',lambda i:c[i]<=sm[i] and v[i]<20); bucket('down + VIX 20-30',lambda i:c[i]<=sm[i] and 20<=v[i]<30); bucket('down + VIX 30-40',lambda i:c[i]<=sm[i] and 30<=v[i]<40); bucket('down + VIX 40+',lambda i:c[i]<=sm[i] and v[i]>=40)
print('CALENDAR YEAR  S&P TR / PUT / BXMD')
def yr(ser):
    o={}
    for d in sorted(ser):
        if d.year>=1996: o[d.year]=ser[d]
    return {y:o[y]/o[y-1]-1 for y in o if y-1 in o}
a,b,cc=yr(TR),yr(S['PUT']),yr(S['BXMD']); print(' '.join(f"{y%100:02d}:{a[y]*100:+.0f}/{b[y]*100:+.0f}/{cc[y]*100:+.0f}" for y in a if y in b and y in cc)); ys=[y for y in a if y in b]; print('PUT beat S&P in',sum(b[y]>a[y] for y in ys),'of',len(ys),'years; in down years',[(y,round(a[y]*100),round(b[y]*100)) for y in ys if a[y]<0])
