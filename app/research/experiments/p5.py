import sys
sys.path.insert(0,'.')
exec(open('app/research/experiments/p4.py').read().split("if __name__")[0])
LEV={L2[u] for u in U}
def audit(name,decide,**kw):
    st=dict(g=0,e=0,calls=0,days=0,worst=0); prev=[False]
    def tr(k,sh,v):
        g=e=req=0
        for s,q in sh.items():
            if s=='CASH': continue
            x=q*m.c[s][k]; g+=x; e+=x*(2 if s in LEV else 1); req+=x*(.6 if s in LEV else .3)
        st['g']=max(st['g'],g/v); st['e']=max(st['e'],e/v); r=req/v; st['worst']=max(st['worst'],r)
        c=r>1
        if c: st['days']+=1
        if c and not prev[0]: st['calls']+=1
        prev[0]=c
    r=run(name,m,decide,idle='CASH',track=tr,**kw); show(r)
    print(f"   peak holdings {st['g']:.2f}x equity · peak market exposure {st['e']:.2f}x · maintenance need peak {st['worst']*100:.0f}% of equity · margin-call episodes {st['calls']} ({st['days']} days)")
    return r
audit('P: Trend QQQ + F adds 25% 2x (2x cap)',P(BW))
audit('P: no borrowing (1x holdings cap)',P(BW),max_gross=1.0)
audit('P: adds 15%',P(BW,.15))
audit('P: adds 15%, no borrowing',P(BW,.15),max_gross=1.0)
audit('P: adds 10%, no borrowing',P(BW,.10),max_gross=1.0)
audit('Q: F alone 25% in 2x',Q(BW))
def P1x(w,add=.25):
    fl=tf('QQQ')
    def d(k,h):
        x={'QQQ':1.} if fl[k] else {}
        for u in U:
            if w[u][k]: x[u]=x.get(u,0)+add
        return x
    return d
audit('Trend QQQ + F adds 25% in NORMAL ETFs',P1x(BW))
audit('Trend QQQ + F adds 25% normal, no borrowing',P1x(BW),max_gross=1.0)
