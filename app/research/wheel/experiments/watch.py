import gzip, json, re, numpy as np, pandas as pd
from datetime import date, timedelta
from app import settings
from app.research.wheel.fetch import DAILY, DIR
from app.research.wheel.panel import BANKRUPT
settings.load_env(); a=settings.alpaca_settings()
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionChainRequest
top=json.loads((DIR/'top500.json').read_text()); mo=max(m for m in top if m<='2026-10'); SAME={'GOOG':'GOOGL','FB':'META'}
A={x['s']:x for x in json.loads((DIR/'assets.json').read_text())}; rows=[]; seen=set()
for rk,s in enumerate(top[mo][:100]):
    n=SAME.get(s,s)
    if n in seen or s in BANKRUPT or not (DAILY/f'{s}.json.gz').exists(): continue
    seen.add(n); x=pd.DataFrame(json.load(gzip.open(DAILY/f'{s}.json.gz','rt')),columns=list('tohlcv')); 
    if len(x)<200: continue
    c=x.c; r=c.pct_change(); rv=r.tail(60).std()*252**.5; hi=c.tail(252).max(); sm=c.tail(200).mean(); worst=r.tail(252).min()
    why=[]
    if not .2<=rv<=.6: why.append(f'vol {rv*100:.0f}%')
    if c.iloc[-1]<.75*hi: why.append(f'{(1-c.iloc[-1]/hi)*100:.0f}% off high')
    if worst<=-.2: why.append(f'{worst*100:.0f}% one-day drop')
    if c.iloc[-1]<=sm: why.append('below 200-day')
    rows.append(dict(s=s,rank=rk+1,name=(A.get(s) or {}).get('name','')[:30],last=x.t.iloc[-1],px=float(c.iloc[-1]),rv=rv,off=1-c.iloc[-1]/hi,worst=worst,why=', '.join(why)))
D=pd.DataFrame(rows); ok=D[D.why==''].reset_index(drop=True); print('top-100 unique',len(D),'pass rule',len(ok),'data through',D['last'].max())
o=OptionHistoricalDataClient(a.api_key,a.secret_key); t=date(2026,11,21); out=[]
for _,r in ok.head(24).iterrows():
    ch=o.get_option_chain(OptionChainRequest(underlying_symbol=r.s,type='put',expiration_date_gte=t+timedelta(days=25),expiration_date_lte=t+timedelta(days=50))); best={}
    for k,v in ch.items():
        m=re.fullmatch(r'[A-Z]+(\d{6})P(\d{8})',k)
        if not m or not v.greeks or v.greeks.delta is None or not v.latest_quote or not v.implied_volatility: continue
        d=abs(v.greeks.delta); q=v.latest_quote
        if not .15<=d<=.35 or not q.bid_price or not q.ask_price: continue
        ex=date(2000+int(m[1][:2]),int(m[1][2:4]),int(m[1][4:])); best.setdefault(ex,[]).append((abs(d-.25),int(m[2])/1000,q.bid_price,q.ask_price,d,v.implied_volatility))
    if not best: out.append(dict(s=r.s)); continue
    ex=min(best,key=lambda e:abs((e-t).days-35)); _,K,b,ak,d,iv=min(best[ex]); dte=(ex-t).days
    out.append(dict(s=r.s,K=K,dte=dte,bid=b,ask=ak,delta=d,iv=iv,coll=K*100,prem=b*100,ann=b/K*365/dte,be=(K-b)/r.px-1,spr=(ak-b)/((ak+b)/2)))
W=ok.head(24).merge(pd.DataFrame(out),on='s',how='left'); W.to_pickle(DIR/'watch2027.pkl'); pd.set_option('display.width',220); pd.set_option('display.max_columns',30)
print(W[['s','rank','px','rv','off','worst','K','coll','prem','ann','iv','be','spr']].round(3).to_string())
print('\nFailed the rule (most liquid first):'); print('; '.join(f"{x.s} ({x.why})" for x in D[D.why!=''].head(32).itertuples()))
