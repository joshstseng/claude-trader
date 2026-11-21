import sys, itertools, pickle
from datetime import date
from multiprocessing import Pool
sys.path.insert(0,'.')
from app.research.system import *
from app.research import yahoo
OUT='app/research/experiments/'
D=Data(market=yahoo.market(list(CORE),date(2000,5,26),date(2026,10,30)))
vx={b.t.date():b.c for b in yahoo.daily('%5EVIX')}; V=[]; last=20
for d in D.m.dates: last=vx.get(d,last); V.append(last)
ERAS=((2001,2008),(2009,2015),(2016,2020),(2021,2026))
EX={'ma5':dict(),'ma10':dict(exit_ma=10),'trail1':dict(exit_ma=None,trail_atr=1.,max_days=250),'trail1.5':dict(exit_ma=None,trail_atr=1.5,max_days=250),'trail2':dict(exit_ma=None,trail_atr=2.,max_days=250),
 'half1R+trail1':dict(exit_ma=None,partial_r=1.,trail_atr=1.,max_days=250),'target2':dict(exit_ma=None,target_r=2.,max_days=60),'target3':dict(exit_ma=None,target_r=3.,max_days=60)}
G=[(vt,tr,k,e) for vt in (0,15,18,20,22,25) for tr in ('up','any') for k in (2.,3.) for e in EX]
def f(a):
    vt,tr,k,e=a
    sp=Spec(name=f'VIX>{vt} {tr} k{k:g} {e}',trend=tr,k_stop=k,**EX[e])
    s=D.signals(sp); s={u:[v and V[i]>vt for i,v in enumerate(x)] for u,x in s.items()}
    r=simulate(D,sp,s); y={k2:v for k2,v in r.years().items() if k2>=2001}
    return dict(a=a,name=sp.name,n=len(r.trades),pf=r.pf,tot=r.total(),dd=r.max_dd(),sh=r.sharpe(),eras=[r.sharpe(x,z) for x,z in ERAS],pos=sum(v>0 for v in y.values()),win=r.win)
if __name__=='__main__':
    with Pool(6) as p: R=p.map(f,G,chunksize=4)
    pickle.dump(R,open(OUT+'h2.pkl','wb'))
    idx={x['a']:x for x in R}
    print('avg Sharpe by VIX floor:',{v:round(sum(x['sh'] for x in R if x['a'][0]==v)/sum(1 for x in R if x['a'][0]==v),2) for v in (0,15,18,20,22,25)})
    print('avg Sharpe by trend:',{v:round(sum(x['sh'] for x in R if x['a'][1]==v)/sum(1 for x in R if x['a'][1]==v),2) for v in ('up','any')})
    print('avg Sharpe by stop:',{v:round(sum(x['sh'] for x in R if x['a'][2]==v)/sum(1 for x in R if x['a'][2]==v),2) for v in (2.,3.)})
    print('avg Sharpe by exit:',{e:round(sum(x['sh'] for x in R if x['a'][3]==e)/sum(1 for x in R if x['a'][3]==e),2) for e in EX})
    print('--- robust: ranked by worst era Sharpe (DD under $10k, 200+ trades)')
    for x in sorted([x for x in R if x['dd']>-10000 and x['n']>=200],key=lambda x:-min(x['eras']))[:16]:
        print(f"{x['name']:34} n={x['n']:4} win {x['win']*100:3.0f}% PF {x['pf']:.2f} ${x['tot']/1000:+6.1f}k DD ${x['dd']/1000:+5.1f}k Sh {x['sh']:.2f} yrs {x['pos']}/26 eras "+' '.join(f'{e:.2f}' for e in x['eras']))
