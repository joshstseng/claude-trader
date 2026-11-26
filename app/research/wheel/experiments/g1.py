import numpy as np
from multiprocessing import Pool
from app.research.wheel import calib
from app.research.wheel.sim import *
from app.research.wheel import bs as bsm
A=calib.samples(); z=calib.trade_zone(A)&(A[:,2]==1); x=A[z]; d=np.abs(bsm.delta(x[:,3],x[:,4],x[:,5],x[:,11],x[:,12],True)); x=x[(d>=.15)&(d<=.35)]; b=calib.fit_final(); iv=np.exp(calib.X(x[:,8],x[:,9],x[:,10],x[:,4]/x[:,3],x[:,5],x[:,2])@b)
lo,hi=.8,1.5
for _ in range(25):
    s=(lo+hi)/2; v=bsm.price(x[:,3],x[:,4],x[:,5],x[:,11],iv*s,True).sum()/x[:,6].sum(); lo,hi=(s,hi) if v<1 else (lo,s)
SCALE=(lo+hi)/2; print('IV scale that matches real premium dollars (15-35 delta puts): %.3f'%SCALE,'| median premium ratio at that scale %.3f'%np.median(bsm.price(x[:,3],x[:,4],x[:,5],x[:,11],iv*SCALE,True)/x[:,6]))
open('data/bars/lab/wheel/scale.txt','w').write(str(SCALE))
M=Mkt(); B=Spec(rank='rand',capital=100000,n_pos=8,weight=.125); F=dict(vix_lo=20,top_n=100,call_delta=.15)
C={'W1 Classic':{},'W2 Fear':F,'W3 QQQ trend+Fear':dict(F,core='QQQ',core_trend=True),'W4 SPY trend+Fear':dict(F,core='SPY',core_trend=True)}
def one(a):
    k,sd=a; r=run(M,replace(B,seed=sd,**k)); return [perf(M,r.eq,y0,y1) for y0,y1 in ((2016,2026),(2016,2021),(2022,2026))]
if __name__=='__main__':
    with Pool(9) as p:
        for sc,lab in ((1.,'base model'),(SCALE,'matched to real premium'),(SCALE*1.05,'optimistic: +5% IV above real')):
            print('---',lab,'IV scale %.3f'%sc)
            for nm,k in C.items():
                o=p.map(one,[(dict(k,iv_scale=sc),s) for s in range(40)],chunksize=4)
                print(f"{nm:22}"+' | '.join(f"{l} {np.median([v[i]['cagr'] for v in o])*100:5.1f}% DD {np.median([v[i]['dd'] for v in o])*100:4.0f}% Sh {np.median([v[i]['sharpe'] for v in o]):.2f}" for i,l in enumerate(('ALL','16-21','22-26'))))
