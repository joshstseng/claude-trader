"""Step 2: the candidate chosen on dev, checked once on the 2013-2018 validation window."""
import pandas as pd

from app.research.swing.lab import carry, ewmac, load, simulate, stats, window

MICRO = ["SP500", "NASDAQ", "RUSSELL", "DOW", "GOLD", "SILVER", "COPPER", "CRUDE_W", "EUR", "GBP", "AUD", "JPY", "CAD", "CHF", "US10", "CORN", "SOYBEAN", "WHEAT"]


def forecast(d):
    t = pd.concat([ewmac(d, n) for n in (16, 32, 64)]).groupby(level=0).mean()
    return (t * .6).add(carry(d) * .4, fill_value=0).where(t.notna())


if __name__ == "__main__":
    d = load(); f = forecast(d)
    t = pd.concat([ewmac(d, n) for n in (16, 32, 64)]).groupby(level=0).mean(); c = carry(d)
    R = {"A all 36 markets": simulate(d, f), "B micro basket 18": simulate(d, f, cols=MICRO),
         "trend only (36)": simulate(d, t), "carry only (36)": simulate(d, c),
         "A at 2x costs": simulate(d, f, cost_mult=2), "B at 2x costs": simulate(d, f, cols=MICRO, cost_mult=2)}
    for w in ("dev", "val"):
        print(f"\n{w.upper()} {'':<22}{'net%':>7}{'vol%':>6}{'Sharpe':>8}{'DD%':>7}{'t':>6}{'corr SPX':>9}")
        spx = window(d.ret["SP500"], w)
        a = "1985" if w == "dev" else None
        for k, r in R.items():
            x = window(r, w).loc[a:]; s = stats(x.net)
            print(f"{k:<26}{s['ret']*100:7.1f}{s['vol']*100:6.1f}{s['sharpe']:8.2f}{s['dd']*100:7.1f}{s['t']:6.1f}{x.net.corr(spx):9.2f}")
        s = stats(spx.loc[a:]); print(f"{'S&P futures (excess)':<26}{s['ret']*100:7.1f}{s['vol']*100:6.1f}{s['sharpe']:8.2f}{s['dd']*100:7.1f}{s['t']:6.1f}")
    print("\nVAL by year, net %")
    y = pd.DataFrame({k: window(r, "val").net.groupby(window(r, "val").index.year).apply(lambda v: ((1 + v).prod() - 1) * 100) for k, r in R.items() if "2x" not in k})
    y["S&P fut"] = window(d.ret["SP500"], "val").groupby(window(d.ret["SP500"], "val").index.year).apply(lambda v: ((1 + v).prod() - 1) * 100)
    print(y.round(1).to_string())
