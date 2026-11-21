import pickle, math
OUT='app/research/experiments/'
dates,R=pickle.load(open(OUT+'g1.pkl','rb'))
yr=[d.year for d in dates]
def sh(x):
    if len(x)<2: return 0
    m=sum(x)/len(x); s=(sum((v-m)**2 for v in x)/len(x))**.5
    return m/s*math.sqrt(252) if s else 0
def dd(x):
    r=p=d=0
    for v in x: r+=v;p=max(p,r);d=min(d,r-p)
    return d
def sub(x,a,z): return [v for v,y in zip(x,yr) if a<=y<=z]
print('--- walk-forward: each year uses the variant with the best Sharpe on all prior years')
wf=[];rows=[]
for Y in range(2019,2027):
    best=max(R,key=lambda q: sh(sub(q[1],2016,Y-1)))
    x=sub(best[1],Y,Y); wf+=x; rows.append((Y,best[0],round(sum(x))))
    print(Y,best[0],f'${sum(x):+,.0f}')
print(f'WALK-FORWARD 2019-2026: ${sum(wf):+,.0f} Sharpe {sh(wf):.2f} DD ${dd(wf):+,.0f}')
fixed=next(q for q in R if q[0]=='k3.0 ma5 br1 up'); x=sub(fixed[1],2019,2026); print(f'Snap unchanged same years: ${sum(x):+,.0f} Sharpe {sh(x):.2f} DD ${dd(x):+,.0f}')
print('--- top by min Sharpe across 3 periods (robust)')
sc=[(min(sh(sub(q[1],2016,2020)),sh(sub(q[1],2021,2023)),sh(sub(q[1],2024,2026))),q) for q in R if q[2]>=200]
for m,q in sorted(sc,key=lambda t:-t[0])[:15]:
    print(f'{q[0]:34} minSh {m:.2f} Sh {sh(q[1]):.2f} ${sum(q[1])/1000:+.1f}k DD ${dd(q[1])/1000:+.1f}k n={q[2]} win {q[4]*100:.0f}% PF {q[3]:.2f}')
