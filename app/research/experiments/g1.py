import sys, json, pickle, time, itertools
from multiprocessing import Pool
sys.path.insert(0,'.')
from app.research.system import *
OUT='app/research/experiments/'
D=Data()
EX={
 'ma5':dict(),
 'trail.75':dict(exit_ma=None,trail_atr=.75,max_days=250),
 'trail1':dict(exit_ma=None,trail_atr=1.,max_days=250),
 'trail1.5':dict(exit_ma=None,trail_atr=1.5,max_days=250),
 'trail2':dict(exit_ma=None,trail_atr=2.,max_days=250),
 'trail1 after1R':dict(exit_ma=None,trail_atr=1.,trail_after_r=1.,max_days=250),
 'BE1R+trail2':dict(exit_ma=None,be_after_r=1.,trail_atr=2.,max_days=250),
 'half@.5R+trail1':dict(exit_ma=None,partial_r=.5,trail_atr=1.,max_days=250),
 'half@1R+trail1':dict(exit_ma=None,partial_r=1.,trail_atr=1.,max_days=250),
 'half@1R+trail2':dict(exit_ma=None,partial_r=1.,trail_atr=2.,max_days=250),
 'half@1R+BE+trail2':dict(exit_ma=None,partial_r=1.,be_after_r=1.,trail_atr=2.,max_days=250),
 'half@2R+trail2':dict(exit_ma=None,partial_r=2.,trail_atr=2.,max_days=250),
 'half@1R+ma5':dict(partial_r=1.),
 'target1':dict(exit_ma=None,target_r=1.,max_days=60),
 'target2':dict(exit_ma=None,target_r=2.,max_days=60),
 'target3':dict(exit_ma=None,target_r=3.,max_days=60),
 'trail1+noprog3':dict(exit_ma=None,trail_atr=1.,no_progress_days=3,max_days=250),
 'trail1+noprog5':dict(exit_ma=None,trail_atr=1.,no_progress_days=5,max_days=250),
 'trail1 max10d':dict(exit_ma=None,trail_atr=1.,max_days=10),
 'trail1 max20d':dict(exit_ma=None,trail_atr=1.,max_days=20),
}
GRID=[]
for k in (1.5,2.,3.):
  for en,e in EX.items():
    for br in (1,2,3):
      for tr in ('up','any'):
        GRID.append(Spec(name=f'k{k} {en} br{br} {tr}',k_stop=k,breadth=br,trend=tr,**e))
def f(sp):
    r=simulate(D,sp)
    return (sp.name,r.daily,len(r.trades),r.pf,r.win)
if __name__=='__main__':
    t=time.time()
    with Pool(6) as p: R=p.map(f,GRID,chunksize=4)
    pickle.dump((D.m.dates,R),open(OUT+'g1.pkl','wb'))
    print('variants',len(R),round(time.time()-t),'s')
