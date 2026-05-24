from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Set
from zoneinfo import ZoneInfo

import pandas as pd

from broker_adapter import OrderRequest, build_broker
from sbi_collector import collect_exports
from sbi_importer import import_sbi_exports
from semi_auto import (
    compute_candidates,
    export_for_sbi,
    export_report,
    load_config,
    load_watchlist,
    size_positions,
)


def ensure_csv(path: Path, columns: list[str]) -> None:
    if path.exists():
        return
    pd.DataFrame(columns=columns).to_csv(path, index=False)


def load_open_position_codes(base: Path, config: Dict) -> Set[str]:
    path = base / str(config["positions_csv"])
    ensure_csv(path, ["code", "name", "qty", "entry_price", "entry_date", "status"])
    df = pd.read_csv(path, dtype={"code": str})
    if df.empty:
        return set()
    if "status" not in df.columns:
        df["status"] = "OPEN"
    open_df = df[df["status"].astype(str).str.upper() == "OPEN"].copy()
    return set(open_df["code"].astype(str).str.zfill(4).tolist())


def today_realized_pnl(base: Path, config: Dict, now: datetime) -> float:
    path = base / str(config["fills_csv"])
    ensure_csv(path, ["fill_date", "code", "side", "qty", "price", "realized_pnl_jpy"])
    df = pd.read_csv(path, dtype={"code": str})
    if df.empty or "realized_pnl_jpy" not in df.columns:
        return 0.0

    today = now.date().isoformat()
    day_df = df[df["fill_date"].astype(str) == today]
    if day_df.empty:
        return 0.0
    return float(pd.to_numeric(day_df["realized_pnl_jpy"], errors="coerce").fillna(0).sum())


def append_audit(base: Path, config: Dict, row: Dict) -> None:
    path = base / str(config["audit_log_csv"])
    fields = [
        "timestamp",
        "event",
        "code",
        "qty",
        "status",
        "message",
        "run_mode",
    ]

    new_file = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if new_file:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in fields})


def sync_sbi_exports(base: Path, config: Dict, now: datetime, run_mode: str) -> None:
    collect_cfg = config.get("sbi_collect", {})
    if bool(collect_cfg.get("enabled", True)):
        try:
            src = Path(str(collect_cfg.get("source_dir", ""))).expanduser()
            dst = base / str(config.get("sbi_import", {}).get("input_dir", "sbi_exports"))
            stats = collect_exports(
                download_dir=src,
                target_dir=dst,
                patterns=list(collect_cfg.get("patterns", ["*.csv"])),
                max_files=int(collect_cfg.get("max_files", 20)),
            )
            append_audit(
                base,
                config,
                {
                    "timestamp": now.isoformat(timespec="seconds"),
                    "event": "SBI_COLLECT",
                    "status": "OK",
                    "message": f"found={stats['found']} copied={stats['copied']} skipped={stats['skipped']}",
                    "run_mode": run_mode,
                },
            )
        except Exception as exc:  # noqa: BLE001
            append_audit(
                base,
                config,
                {
                    "timestamp": now.isoformat(timespec="seconds"),
                    "event": "SBI_COLLECT",
                    "status": "ERROR",
                    "message": str(exc),
                    "run_mode": run_mode,
                },
            )

    imp_cfg = config.get("sbi_import", {})
    if not bool(imp_cfg.get("enabled", True)):
        return

    import_dir = base / str(imp_cfg.get("input_dir", "sbi_exports"))
    import_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = import_sbi_exports(
            base_dir=base,
            import_dir=import_dir,
            positions_patterns=list(imp_cfg.get("positions_patterns", ["*pos*.csv", "*保有*.csv"])),
            fills_patterns=list(imp_cfg.get("fills_patterns", ["*fill*.csv", "*約定*.csv", "*履歴*.csv"])),
            positions_out=base / str(config["positions_csv"]),
            fills_out=base / str(config["fills_csv"]),
        )
        message = f"imported={','.join(result.keys())}" if result else "imported=none"
        append_audit(
            base,
            config,
            {
                "timestamp": now.isoformat(timespec="seconds"),
                "event": "SBI_SYNC",
                "status": "OK",
                "message": message,
                "run_mode": run_mode,
            },
        )
    except Exception as exc:  # noqa: BLE001
        append_audit(
            base,
            config,
            {
                "timestamp": now.isoformat(timespec="seconds"),
                "event": "SBI_SYNC",
                "status": "ERROR",
                "message": str(exc),
                "run_mode": run_mode,
            },
        )


def run_cycle(base: Path, run_mode: str) -> int:
    config = load_config(base)
    tz = ZoneInfo(str(config.get("timezone", "Asia/Tokyo")))
    now = datetime.now(tz)

    sync_sbi_exports(base, config, now, run_mode)

    kill_switch = base / str(config.get("kill_switch_file", "KILL_SWITCH"))
    if kill_switch.exists():
        append_audit(
            base,
            config,
            {
                "timestamp": now.isoformat(timespec="seconds"),
                "event": "HALT",
                "status": "SKIPPED",
                "message": f"Kill switch found: {kill_switch.name}",
                "run_mode": run_mode,
            },
        )
        return 0

    realized = today_realized_pnl(base, config, now)
    daily_limit = -abs(float(config.get("daily_loss_limit_jpy", 20000)))
    if realized <= daily_limit:
        append_audit(
            base,
            config,
            {
                "timestamp": now.isoformat(timespec="seconds"),
                "event": "DAILY_STOP",
                "status": "SKIPPED",
                "message": f"Realized PnL {realized:.0f} <= limit {daily_limit:.0f}",
                "run_mode": run_mode,
            },
        )
        return 0

    watch = load_watchlist(base / str(config["watchlist_csv"]))
    ranked = compute_candidates(watch, config)

    open_codes = load_open_position_codes(base, config)
    if not ranked.empty:
        ranked = ranked[~ranked["code"].astype(str).str.zfill(4).isin(open_codes)].copy()

    picks = size_positions(ranked, config)
    export_for_sbi(base, picks, config)
    export_report(base, picks, config)

    broker = build_broker(config, base)
    for _, row in picks.iterrows():
        order = OrderRequest(
            code=str(row["code"]),
            side="BUY",
            qty=int(row["qty"]),
            order_type="LIMIT",
            limit_price=float(row["entry_price"]),
            stop_loss=float(row["stop_price"]),
            take_profit=float(row["take_profit_price"]),
            reason=f"prob={float(row['probability']):.3f}, score={float(row['score']):.3f}",
        )
        result = broker.place_order(order)
        append_audit(
            base,
            config,
            {
                "timestamp": now.isoformat(timespec="seconds"),
                "event": "ORDER",
                "code": order.code,
                "qty": order.qty,
                "status": result.status,
                "message": result.message,
                "run_mode": run_mode,
            },
        )

    append_audit(
        base,
        config,
        {
            "timestamp": now.isoformat(timespec="seconds"),
            "event": "RUN_COMPLETE",
            "status": "OK",
            "message": f"picks={len(picks)}",
            "run_mode": run_mode,
        },
    )
    return len(picks)


def is_business_day_jst(now: datetime) -> bool:
    return now.weekday() < 5


def run_daemon(base: Path) -> None:
    config = load_config(base)
    tz = ZoneInfo(str(config.get("timezone", "Asia/Tokyo")))
    hh, mm = str(config.get("run_time", "07:45")).split(":")
    target_hour = int(hh)
    target_min = int(mm)

    last_run_day = ""
    while True:
        now = datetime.now(tz)
        day_key = now.date().isoformat()
        if (
            is_business_day_jst(now)
            and now.hour == target_hour
            and now.minute == target_min
            and day_key != last_run_day
        ):
            run_cycle(base, run_mode="daemon")
            last_run_day = day_key
        time.sleep(30)


def main() -> None:
    parser = argparse.ArgumentParser(description="Automated trading runner")
    parser.add_argument("--once", action="store_true", help="Run only one cycle now")
    args = parser.parse_args()

    base = Path(__file__).resolve().parent
    if args.once:
        count = run_cycle(base, run_mode="once")
        print(f"Completed one cycle. picks={count}")
        return

    print("Daemon mode started. Press Ctrl+C to stop.")
    run_daemon(base)


if __name__ == "__main__":
    main()
