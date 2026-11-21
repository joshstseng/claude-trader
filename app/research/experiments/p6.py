import sys
sys.path.insert(0,'.')
exec(open('app/research/experiments/p4.py').read().split("if __name__")[0])
q=run('Buy & hold QQQ',m,lambda k,h:{'QQQ':1.}); s=run('Buy & hold SPY',m,lambda k,h:{'SPY':1.}); b=run('Defensive',m,Q(BW),idle='CASH'); show(q);show(s);show(b)
print('-- neighbours')
for vt in (15,18,22,25): show(run(f'VIX>{vt}',m,Q(F(vt=vt)),idle='CASH'))
for tr in (1.,1.25,1.75,2.): show(run(f'trail {tr}',m,Q(F(tr=tr)),idle='CASH'))
for k in (2.,4.): show(run(f'start stop {k}',m,Q(F(k=k)),idle='CASH'))
for a in (.1,.15,.2,.3): show(run(f'size {a:.0%}',m,Q(BW,a),idle='CASH'))
print('-- costs')
PF.SLIP=.0005; show(run('5bp',m,Q(BW),idle='CASH')); PF.SLIP=.001; show(run('10bp',m,Q(BW),idle='CASH')); PF.SLIP=.0001
def yr(r):
    o={}; prev=r.equity[0]; cy=r.dates[0].year
    for d,e in zip(r.dates,r.equity):
        if d.year!=cy: cy=d.year
        o[d.year]=e
    ys=sorted(o); return {y:o[y]/(o[y-1] if y-1 in o else r.equity[0])-1 for y in ys}
Y,YS,YQ=yr(b),yr(s),yr(q)
print('year def spy qqq'); print(' '.join(f"{y%100:02d}:{Y[y]*100:+.0f}/{YS[y]*100:+.0f}/{YQ[y]*100:+.0f}" for y in Y if y>=2001))
ys=[y for y in Y if y>=2001]; print('positive years',sum(Y[y]>0 for y in ys),'/',len(ys),'beats SPY',sum(Y[y]>YS[y] for y in ys),'beats QQQ',sum(Y[y]>YQ[y] for y in ys),'worst',min(Y[y] for y in ys))
print('in down years for SPY:',{y:(round(Y[y]*100),round(YS[y]*100)) for y in ys if YS[y]<0})
print('5y windows beating QQQ/SPY',round(roll(b,q)[0]),round(roll(b,s)[0]))
print('time holding any dip position %.0f%%'%(100*sum(any(BW[u][k] for u in U) for k in range(len(m.dates)))/len(m.dates)))
