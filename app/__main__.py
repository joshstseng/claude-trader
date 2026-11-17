"""python -m app: shows what would run. The real daily routine arrives in sub-step 1a.5."""

from app import settings, strategies


def main() -> int:
    settings.load_env()
    rules = settings.risk_rules()
    bots = strategies.load_enabled()
    print("claude-trader (Step 1a: alerts only, no orders)")
    print(f"  paper only: {rules['paper']}")
    print(f"  account ${rules['budget']:,}, max loss/trade ${rules['max_loss_per_trade_usd']}, "
          f"daily loss limit ${rules['max_daily_loss_usd']}")
    for s in bots:
        w = s.settings["scan_window"]
        print(f"  [{s.id.upper()}] {s.name}: scan {w['start']}-{w['end']} ET, "
              f"stop {s.settings['exit']['stop']}, target {s.settings['exit']['target']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
