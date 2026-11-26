import numpy as np
from datetime import date
from app.research.wheel import calib, bs
from app.research.wheel.panel import clean
A=calib.samples(); P=clean(); yr=np.array([P.days[int(i)].year for i in A[:,1]]); print('real option observations',len(A),'names',len(set(A[:,0])),'by year',{y:int((yr==y).sum()) for y in (2024,2025,2026)})
tr=yr==2024; te=yr>=2025; b=calib.fit(A,tr); print('coef (fit on 2024)',np.round(b,3))
def pred(b,x): return calib.predict.__wrapped__(b,x) if 0 else np.exp(calib.X(x[:,8],x[:,9],x[:,10],x[:,4]/x[:,3],x[:,5],x[:,2])@b)
for nm,mask in (('in-sample 2024',tr),('OUT-OF-SAMPLE 2025-26',te)):
    x=A[mask]; iv=pred(b,x); e=np.log(iv/x[:,12]); pr=bs.price(x[:,3],x[:,4],x[:,5],x[:,11],iv,True); 
    print(nm,'IV median ratio model/real %.3f, typical error %.1f%%'%(np.exp(np.median(e)),np.median(np.abs(e))*100))
x=A[te & (A[:,2]==1)]; iv=pred(b,x); d=np.abs(bs.delta(x[:,3],x[:,4],x[:,5],x[:,11],x[:,12],True)); m=(d>=.15)&(d<=.35); x=x[m]; iv=iv[m]
mp=bs.price(x[:,3],x[:,4],x[:,5],x[:,11],iv,True); r=mp/x[:,6]; print('15-35 delta puts, 2025-26: n',len(x),'model premium / real premium: median %.3f, mean %.3f, 10th %.2f, 90th %.2f, total-dollar ratio %.3f'%(np.median(r),np.mean(r),*np.percentile(r,[10,90]),mp.sum()/x[:,6].sum()))
for lo,hi in ((0,.3),(.3,.5),(.5,.8),(.8,9)):
    q=(x[:,12]>=lo)&(x[:,12]<hi); print(' real IV %.0f-%.0f%%: n %d median ratio %.3f dollar ratio %.3f'%(lo*100,min(hi,9)*100,q.sum(),np.median(r[q]),mp[q].sum()/x[q,6].sum()))
rv=x[:,9]; ivr=x[:,12]/rv; print('implied/realized-60d median %.2f'%np.median(ivr))
print('--- by the MODEL\'s own IV (what a backtest can actually sort on), 2025-26, 15-35 delta puts')
for lo,hi in ((0,.3),(.3,.5),(.5,.8),(.8,9)):
    q=(iv>=lo)&(iv<hi); print(' model IV %.0f-%.0f%%: n %d median premium ratio %.3f dollar ratio %.3f, IV ratio %.3f'%(lo*100,min(hi,9)*100,q.sum(),np.median(r[q]),mp[q].sum()/x[q,6].sum(),np.median(iv[q]/x[q,12])))
