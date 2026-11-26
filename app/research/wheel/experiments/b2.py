import gzip, json, math, numpy as np
from datetime import date
from collections import defaultdict
from app.research.wheel import calib, bs
from app.research.wheel.panel import clean
from app.research.wheel.fetch import DIR
A=calib.samples(); P=clean(); yr=np.array([P.days[int(i)].year for i in A[:,1]]); z=calib.trade_zone(A)
b=calib.fit(A,z&(yr==2024)); x=A[z&(yr>=2025)&(A[:,2]==1)]; iv=np.exp(calib.X(x[:,8],x[:,9],x[:,10],x[:,4]/x[:,3],x[:,5],x[:,2])@b); mp=bs.price(x[:,3],x[:,4],x[:,5],x[:,11],iv,True); r=mp/x[:,6]
print('Fit 2024 on 10-45 delta; test puts 2025-26: n',len(x),'median premium ratio %.3f, dollar ratio %.3f'%(np.median(r),mp.sum()/x[:,6].sum()))
for lo,hi in ((0,.3),(.3,.5),(.5,.8),(.8,9)):
    q=(iv>=lo)&(iv<hi); print(' model IV %d-%d%%: ratio median %.3f dollar %.3f'%(lo*100,min(hi,9)*100,np.median(r[q]),mp[q].sum()/x[q,6].sum()))
beta=calib.fit_final(); print('final beta',np.round(beta,3))
# real put selling, name by name, on real traded prices
rv20,rv60=calib.features(P); vix,rf=calib.macro(P.days); ix={d:i for i,d in enumerate(P.days)}; pos={s:j for j,s in enumerate(P.names)}
R=json.load(gzip.open(DIR/'raw2024.json.gz','rt')); raw={s:{date.fromisoformat(q[0]):q[4] for q in v} for s,v in R.items()}
s200=None; import pandas as pd; s200=pd.DataFrame(P.C).rolling(200,min_periods=150).mean().values
T=[]
for fn in sorted((DIR/'opt').glob('*.json.gz')):
    doc=json.load(gzip.open(fn,'rt')); ex=date.fromisoformat(doc['exp']); by=defaultdict(list)
    for k,m in doc['meta'].items():
        if m['type']=='put' and k in doc['bars']: by[m['u']].append((k,m))
    for u,cs in by.items():
        if u not in raw or u not in pos: continue
        ds=sorted(d for d in raw[u] if d.strftime('%Y-%m')==fn.name[:7])
        if not ds: continue
        d0=ds[0]; S=raw[u][d0]; days=(ex-d0).days/365; best=None
        for k,m in cs:
            b0=[q for q in doc['bars'][k] if q[0]==d0.isoformat() and q[5]>=5]
            if not b0 or m['K']>=S: continue
            iv0=float(bs.implied(np.array([b0[0][4]]),np.array([S]),np.array([m['K']]),np.array([days]),rf[ix[d0]],True)[0])
            if np.isnan(iv0): continue
            dl=abs(float(bs.delta(S,m['K'],days,rf[ix[d0]],iv0,True)))
            if .15<=dl<=.35 and (best is None or abs(dl-.25)<abs(best[0]-.25)): best=(dl,k,m['K'],b0[0][4],iv0,b0[0][5])
        if not best: continue
        xs=[d for d in raw[u] if d<=ex]; dx=max(xs)
        if (ex-dx).days>3: continue
        Sx=raw[u][dx]
        if abs(np.log(Sx/S))>1.0: continue
        dl,k,K,px,iv0,vol=best; prem=px*.95-.0065; pay=prem-max(K-Sx,0); j=pos[u]; i=ix[d0]
        T.append(dict(u=u,m=fn.name[:7],d=d0,K=K,S=S,iv=iv0,dte=days*365,prem=prem,ret=pay/K,stock=Sx/S-1,win=pay>0,assigned=Sx<K,vix=vix[i],trend=(P.C[i,j]>s200[i,j]) if not np.isnan(s200[i,j]) else None,ivrv=iv0/rv60[i,j] if rv60[i,j]>0 else np.nan))
D=pd.DataFrame(T); D.to_pickle(DIR/'real_puts.pkl'); print('REAL puts held to expiry:',len(D),'names',D.u.nunique(),'avg DTE %.0f'%D.dte.mean())
def s(g): 
    ann=365/g.dte.mean(); return f"n {len(g):5} win {g.win.mean()*100:3.0f}% assigned {g.assigned.mean()*100:3.0f}% | put return/trade {g.ret.mean()*100:+5.2f}% (median {g.ret.median()*100:+5.2f}%) | same stock {g.stock.mean()*100:+5.2f}% | worst {g.ret.min()*100:5.0f}%"
print('ALL',s(D))
for lo,hi in ((0,.3),(.3,.45),(.45,.6),(.6,.8),(.8,1.2),(1.2,9)): print(f' IV {lo*100:.0f}-{min(hi,9)*100:.0f}%',s(D[(D.iv>=lo)&(D.iv<hi)]))
for lo,hi in ((0,15),(15,20),(20,30),(30,99)): g=D[(D.vix>=lo)&(D.vix<hi)]; print(f' VIX {lo}-{hi}',s(g) if len(g) else 'none')
for v,l in ((True,'above 200d'),(False,'below 200d')): print(' stock',l,s(D[D.trend==v]))
for lo,hi in ((0,.9),(.9,1.1),(1.1,1.3),(1.3,9)): print(f' IV/RV {lo}-{hi}',s(D[(D.ivrv>=lo)&(D.ivrv<hi)]))
print(D.groupby('m').agg(n=('ret','size'),put=('ret','mean'),stock=('stock','mean')).round(4).to_string())
