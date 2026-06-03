from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime
import os
from pathlib import Path
from typing import Dict, Set
from zoneinfo import ZoneInfo

import pandas as pd

from broker_adapter import OrderRequest, build_broker
from line_notify import send_line_notify
from sbi_collector import collect_exports
from sbi_importer import import_sbi_exports
from semi_auto import (
    compute_candidates,
    evaluate_sell_candidates,
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
    df = load_open_positions(base, config)
    if df.empty:
        return set()
    return set(df["code"].astype(str).str.zfill(4).tolist())


def load_open_positions(base: Path, config: Dict) -> pd.DataFrame:
    path = base / str(config["positions_csv"])
    ensure_csv(path, ["code", "name", "qty", "entry_price", "entry_date", "status"])
    df = pd.read_csv(path, dtype={"code": str})
    if df.empty:
        return pd.DataFrame(columns=["code", "name", "qty", "entry_price", "entry_date", "status"])
    if "status" not in df.columns:
        df["status"] = "OPEN"
    open_df = df[df["status"].astype(str).str.upper() == "OPEN"].copy()
    open_df["code"] = open_df["code"].astype(str).str.zfill(4)
    return open_df


def today_realized_pnl(base: Path, config: Dict, now: datetime) -> float:
    path = base / str(config["fills_csv"])
    ensure_csv(path, ["fill_date", "code", "side", "qty", "price", "realized_pnl_jpy"])
    try:
        df = pd.read_csv(path, dtype={"code": str}, engine="python", on_bad_lines="skip")
    except pd.errors.ParserError:
        df = pd.DataFrame(columns=["fill_date", "code", "side", "qty", "price", "realized_pnl_jpy"])
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


def build_order_summary(rows: pd.DataFrame, limit: int = 5) -> str:
    if rows.empty:
        return "なし"

    items = []
    for _, row in rows.head(limit).iterrows():
        items.append(f"{str(row['code']).zfill(4)} {row['name']} {int(row['qty'])}株")

    remaining = len(rows) - min(len(rows), limit)
    if remaining > 0:
        items.append(f"...他{remaining}件")
    return " / ".join(items)


def notify_line(base: Path, config: Dict, title: str, body: str) -> None:
    line_cfg = config.get("line_messaging", {})
    if not bool(line_cfg.get("enabled", True)):
        return

    token_env = str(line_cfg.get("channel_token_env", "LINE_CHANNEL_ACCESS_TOKEN"))
    to_env = str(line_cfg.get("to_env", "LINE_TO_ID"))
    token = os.getenv(token_env, "")
    to = os.getenv(to_env, "")
    if not token or not to:
        append_audit(
            base,
            config,
            {
                "timestamp": datetime.now(ZoneInfo(str(config.get("timezone", "Asia/Tokyo")))).isoformat(timespec="seconds"),
                "event": "LINE_MSG_SKIP",
                "status": "SKIPPED",
                "message": f"Missing env token={token_env} to={to_env}",
                "run_mode": "",
            },
        )
        return

    try:
        status, response_body = send_line_notify(token, to, f"{title}\n{body}")
        append_audit(
            base,
            config,
            {
                "timestamp": datetime.now(ZoneInfo(str(config.get("timezone", "Asia/Tokyo")))).isoformat(timespec="seconds"),
                "event": "LINE_MSG",
                "status": "OK" if 200 <= int(status) < 300 else "ERROR",
                "message": f"http={status} {response_body}",
                "run_mode": "",
            },
        )
    except Exception as exc:  # noqa: BLE001
        append_audit(
            base,
            config,
            {
                "timestamp": datetime.now(ZoneInfo(str(config.get("timezone", "Asia/Tokyo")))).isoformat(timespec="seconds"),
                "event": "LINE_MSG",
                "status": "ERROR",
                "message": str(exc),
                "run_mode": "",
            },
        )


def notify_cycle_success(base: Path, config: Dict, run_mode: str, picks: pd.DataFrame, sell_signals: pd.DataFrame, open_positions: pd.DataFrame) -> None:
    title = f"Trading run {run_mode} OK"
    body_lines = [
        f"BUY: {len(picks)}件",
        f"SELL: {len(sell_signals)}件",
        f"OPEN: {len(open_positions)}件",
        f"BUY一覧: {build_order_summary(picks)}",
        f"SELL一覧: {build_order_summary(sell_signals)}",
    ]
    notify_line(base, config, title, "\n".join(body_lines))


def notify_cycle_failure(base: Path, config: Dict, run_mode: str, exc: Exception) -> None:
    title = f"Trading run {run_mode} FAILED"
    body = f"{type(exc).__name__}: {exc}"
    notify_line(base, config, title, body)


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

    open_positions = load_open_positions(base, config)
    open_codes = set(open_positions["code"].astype(str).str.zfill(4).tolist()) if not open_positions.empty else set()
    if not ranked.empty:
        ranked = ranked[~ranked["code"].astype(str).str.zfill(4).isin(open_codes)].copy()

    max_total_open = int(config.get("max_total_open_positions", 0) or 0)
    remaining_slots = int(config.get("max_new_positions_per_day", 3))
    if max_total_open > 0:
        remaining_slots = max(0, max_total_open - len(open_positions))
        if remaining_slots == 0:
            append_audit(
                base,
                config,
                {
                    "timestamp": now.isoformat(timespec="seconds"),
                    "event": "ENTRY_CAP_REACHED",
                    "status": "SKIPPED",
                    "message": f"open_positions={len(open_positions)} cap={max_total_open}",
                    "run_mode": run_mode,
                },
            )

    if ranked.empty or remaining_slots <= 0:
        picks = pd.DataFrame()
    else:
        sizing_config = dict(config)
        sizing_config["max_new_positions_per_day"] = min(int(config.get("max_new_positions_per_day", 3)), remaining_slots)
        picks = size_positions(ranked, sizing_config)
    sell_signals = evaluate_sell_candidates(open_positions, config)
    export_for_sbi(base, picks, config, sell_signals)
    export_report(base, picks, config, sell_signals)

    broker = build_broker(config, base)

    for _, row in sell_signals.iterrows():
        order = OrderRequest(
            code=str(row["code"]),
            side="SELL",
            qty=int(row["qty"]),
            order_type="LIMIT",
            limit_price=float(row["exit_price"]),
            stop_loss=0.0,
            take_profit=0.0,
            reason=str(row.get("memo", "SELL signal")),
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
                "message": f"side=SELL {result.message}",
                "run_mode": run_mode,
            },
        )

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
                "message": f"side=BUY {result.message}",
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

    notify_cycle_success(base, config, run_mode, picks, sell_signals, open_positions)
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
            try:
                run_cycle(base, run_mode="daemon")
            except Exception as exc:  # noqa: BLE001
                config = load_config(base)
                notify_cycle_failure(base, config, "daemon", exc)
            last_run_day = day_key
        time.sleep(30)


def main() -> None:
    parser = argparse.ArgumentParser(description="Automated trading runner")
    parser.add_argument("--once", action="store_true", help="Run only one cycle now")
    args = parser.parse_args()

    base = Path(__file__).resolve().parent
    if args.once:
        try:
            count = run_cycle(base, run_mode="once")
            print(f"Completed one cycle. picks={count}")
        except Exception as exc:  # noqa: BLE001
            config = load_config(base)
            notify_cycle_failure(base, config, "once", exc)
            raise
        return

    print("Daemon mode started. Press Ctrl+C to stop.")
    run_daemon(base)


if __name__ == "__main__":
    main()
