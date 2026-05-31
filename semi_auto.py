from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd
import yfinance as yf


@dataclass
class TradeCandidate:
    code: str
    name: str
    ticker: str
    probability: float
    score: float
    entry_price: float
    stop_price: float
    take_profit_price: float
    qty: int
    risk_per_share: float
    estimated_max_loss: float


def load_config(base: Path) -> Dict:
    config_path = base / "config.json"
    with config_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    up_avg = up.ewm(alpha=1 / period, min_periods=period).mean()
    down_avg = down.ewm(alpha=1 / period, min_periods=period).mean()
    rs = up_avg / down_avg.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def load_watchlist(path: Path) -> pd.DataFrame:
    watch = pd.read_csv(path, dtype={"code": str})
    watch["code"] = watch["code"].str.zfill(4)
    watch = watch.drop_duplicates(subset=["code"]).head(100).copy()
    watch["ticker"] = watch["code"] + ".T"
    return watch


def to_1d_series(df: pd.DataFrame, col: str) -> pd.Series:
    data = df[col]
    if isinstance(data, pd.DataFrame):
        # yfinance may return a one-column frame for a single ticker depending on version/settings.
        data = data.iloc[:, 0]
    return pd.to_numeric(data, errors="coerce")


def fetch_features(ticker: str) -> Dict[str, float] | None:
    hist = yf.download(ticker, period="9mo", interval="1d", progress=False, auto_adjust=False)
    if hist.empty or len(hist) < 80:
        return None

    close = to_1d_series(hist, "Close")
    vol = to_1d_series(hist, "Volume")

    ret5 = close.iloc[-1] / close.iloc[-6] - 1
    ret20 = close.iloc[-1] / close.iloc[-21] - 1
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]
    ma_gap = ma20 / ma60 - 1 if ma60 > 0 else np.nan
    rsi14 = rsi(close, 14).iloc[-1]
    vol20 = close.pct_change().rolling(20).std().iloc[-1] * np.sqrt(252)
    volume_ratio = vol.iloc[-1] / vol.rolling(20).mean().iloc[-1]

    if np.isnan([ret5, ret20, ma_gap, rsi14, vol20, volume_ratio]).any():
        return None

    return {
        "ret5": float(ret5),
        "ret20": float(ret20),
        "ma_gap": float(ma_gap),
        "ma20": float(ma20),
        "rsi14": float(rsi14),
        "vol20": float(vol20),
        "volume_ratio": float(volume_ratio),
        "entry_price": float(close.iloc[-1]),
        "current_price": float(close.iloc[-1]),
    }


def business_days_held(entry_date_raw: object, today: date) -> int:
    try:
        entry = pd.to_datetime(entry_date_raw, errors="coerce")
        if pd.isna(entry):
            return 0
        start = np.datetime64(entry.date())
        end = np.datetime64(today)
        return int(np.busday_count(start, end) + 1)
    except Exception:  # noqa: BLE001
        return 0


def evaluate_sell_candidates(positions: pd.DataFrame, config: Dict) -> pd.DataFrame:
    if positions.empty:
        return pd.DataFrame()

    stop_loss_pct = float(config["stop_loss_pct"])
    tp_pct = float(config["take_profit_pct"])
    min_holding_days = int(config.get("min_holding_days", 2))
    max_holding_days = int(config.get("holding_days_max", 10))
    today = date.today()

    signals = []
    for _, row in positions.iterrows():
        code = str(row.get("code", "")).zfill(4)
        if not code:
            continue

        qty = int(pd.to_numeric(row.get("qty", 0), errors="coerce") or 0)
        if qty <= 0:
            continue

        metrics = fetch_features(f"{code}.T")
        if metrics is None:
            continue

        current_price = float(metrics["current_price"])
        ma20 = float(metrics["ma20"])
        rsi14 = float(metrics["rsi14"])
        entry_price = float(pd.to_numeric(row.get("entry_price", 0.0), errors="coerce") or 0.0)
        days_held = business_days_held(row.get("entry_date", ""), today)

        trigger = ""
        if entry_price > 0:
            stop = entry_price * (1 - stop_loss_pct)
            take_profit = entry_price * (1 + tp_pct)
            if current_price <= stop:
                trigger = "STOP_LOSS"
            elif current_price >= take_profit and days_held >= min_holding_days:
                trigger = "TAKE_PROFIT"

        if not trigger and days_held >= max_holding_days:
            trigger = "TIME_EXIT"

        if not trigger and days_held >= min_holding_days and current_price < ma20 and rsi14 < 45:
            trigger = "MOMENTUM_WEAK"

        if not trigger:
            continue

        signals.append(
            {
                "code": code,
                "name": str(row.get("name", "")),
                "qty": qty,
                "exit_price": current_price,
                "days_held": days_held,
                "rsi14": rsi14,
                "trigger": trigger,
                "memo": f"{trigger}; held={days_held}bd; rsi={rsi14:.1f}",
            }
        )

    return pd.DataFrame(signals)


def compute_candidates(watch: pd.DataFrame, config: Dict) -> pd.DataFrame:
    rows = []
    for _, row in watch.iterrows():
        metrics = fetch_features(row["ticker"])
        if metrics is None:
            continue
        rows.append(
            {
                "code": row["code"],
                "name": row["name"],
                "ticker": row["ticker"],
                **metrics,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Composite score for 2-10 day swing: momentum + trend + participation - volatility.
    df["score"] = (
        0.35 * df["ret20"].rank(pct=True)
        + 0.25 * df["ma_gap"].rank(pct=True)
        + 0.20 * df["volume_ratio"].rank(pct=True)
        + 0.20 * (-df["vol20"]).rank(pct=True)
    )

    z = (df["score"] - df["score"].mean()) / (df["score"].std(ddof=0) + 1e-9)
    df["probability"] = 1 / (1 + np.exp(-z))

    min_prob = float(config["min_probability"])
    df = df[df["probability"] >= min_prob].copy()
    df = df.sort_values("score", ascending=False)
    return df


def size_positions(df: pd.DataFrame, config: Dict) -> pd.DataFrame:
    if df.empty:
        return df

    capital = float(config["capital_jpy"])
    risk_per_trade = float(config["risk_per_trade"])
    stop_loss_pct = float(config["stop_loss_pct"])
    tp_pct = float(config["take_profit_pct"])
    max_new = int(config["max_new_positions_per_day"])

    risk_budget = capital * risk_per_trade
    budget_per_trade = capital / max_new

    sized = []
    for _, row in df.iterrows():
        if len(sized) >= max_new:
            break
        entry = float(row["entry_price"])
        stop = entry * (1 - stop_loss_pct)
        tp = entry * (1 + tp_pct)
        risk_per_share = max(entry - stop, 1e-6)

        qty_risk = int(np.floor(risk_budget / risk_per_share / 100.0) * 100)
        qty_capital = int(np.floor(budget_per_trade / entry / 100.0) * 100)
        qty = max(0, min(qty_risk, qty_capital))
        if qty < 100:
            continue

        sized.append(
            TradeCandidate(
                code=str(row["code"]),
                name=str(row["name"]),
                ticker=str(row["ticker"]),
                probability=float(row["probability"]),
                score=float(row["score"]),
                entry_price=entry,
                stop_price=stop,
                take_profit_price=tp,
                qty=qty,
                risk_per_share=risk_per_share,
                estimated_max_loss=qty * risk_per_share,
            )
        )

    out = pd.DataFrame([c.__dict__ for c in sized])
    return out


def export_for_sbi(base: Path, picks: pd.DataFrame, config: Dict, sell_signals: pd.DataFrame | None = None) -> None:
    output_csv = base / config["output_orders_csv"]
    sell_signals = sell_signals if sell_signals is not None else pd.DataFrame()

    if picks.empty and sell_signals.empty:
        pd.DataFrame(
            columns=[
                "trade_date",
                "broker",
                "code",
                "name",
                "side",
                "order_type",
                "qty",
                "entry_limit",
                "stop_loss",
                "take_profit",
                "holding_days_max",
                "probability",
                "score",
                "estimated_max_loss_jpy",
                "memo",
            ]
        ).to_csv(output_csv, index=False)
        return

    trade_date = str(date.today())
    frames = []

    if not picks.empty:
        frames.append(
            pd.DataFrame(
                {
                    "trade_date": trade_date,
                    "broker": "SBI",
                    "code": picks["code"],
                    "name": picks["name"],
                    "side": "BUY",
                    "order_type": "LIMIT",
                    "qty": picks["qty"].astype(int),
                    "entry_limit": picks["entry_price"].round(1),
                    "stop_loss": picks["stop_price"].round(1),
                    "take_profit": picks["take_profit_price"].round(1),
                    "holding_days_max": int(config["holding_days_max"]),
                    "probability": picks["probability"].round(4),
                    "score": picks["score"].round(4),
                    "estimated_max_loss_jpy": picks["estimated_max_loss"].round(0).astype(int),
                    "memo": "Set reverse stop order in SBI",
                }
            )
        )

    if not sell_signals.empty:
        frames.append(
            pd.DataFrame(
                {
                    "trade_date": trade_date,
                    "broker": "SBI",
                    "code": sell_signals["code"],
                    "name": sell_signals["name"],
                    "side": "SELL",
                    "order_type": "LIMIT",
                    "qty": sell_signals["qty"].astype(int),
                    "entry_limit": sell_signals["exit_price"].round(1),
                    "stop_loss": "",
                    "take_profit": "",
                    "holding_days_max": int(config["holding_days_max"]),
                    "probability": "",
                    "score": "",
                    "estimated_max_loss_jpy": 0,
                    "memo": sell_signals["memo"],
                }
            )
        )

    sbi = pd.concat(frames, ignore_index=True)
    sbi.to_csv(output_csv, index=False)


def export_report(base: Path, picks: pd.DataFrame, config: Dict, sell_signals: pd.DataFrame | None = None) -> None:
    sell_signals = sell_signals if sell_signals is not None else pd.DataFrame()
    report_path = base / config["output_report_md"]
    risk_budget = float(config["capital_jpy"]) * float(config["risk_per_trade"])

    lines = [
        "# Daily Semi-Auto Trading Report",
        "",
        f"- Date: {date.today()}",
        f"- Capital (JPY): {int(config['capital_jpy'])}",
        f"- Risk per trade (JPY): {risk_budget:.0f}",
        f"- Max new positions: {config['max_new_positions_per_day']}",
        f"- Style: Swing {config['min_holding_days']}-{config['holding_days_max']} business days",
        "",
    ]

    if picks.empty:
        lines.extend(
            [
                "## BUY Candidates",
                "",
                "No new BUY candidates met the minimum probability threshold today.",
            ]
        )
    else:
        lines.extend(["## BUY Candidates", "", "| Code | Name | Prob | Qty | Entry | Stop | TP | MaxLoss |", "|---|---|---:|---:|---:|---:|---:|---:|"])
        for _, p in picks.iterrows():
            lines.append(
                f"| {p['code']} | {p['name']} | {p['probability']:.3f} | {int(p['qty'])} | {p['entry_price']:.1f} | {p['stop_price']:.1f} | {p['take_profit_price']:.1f} | {p['estimated_max_loss']:.0f} |"
            )

    lines.extend(["", "## SELL Signals", ""])
    if sell_signals.empty:
        lines.append("No SELL signals for current OPEN positions today.")
    else:
        lines.extend(["| Code | Name | Qty | ExitRef | DaysHeld | RSI14 | Trigger |", "|---|---|---:|---:|---:|---:|---|"])
        for _, s in sell_signals.iterrows():
            lines.append(
                f"| {s['code']} | {s['name']} | {int(s['qty'])} | {float(s['exit_price']):.1f} | {int(s['days_held'])} | {float(s['rsi14']):.1f} | {s['trigger']} |"
            )

    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    base = Path(__file__).resolve().parent
    config = load_config(base)
    watch = load_watchlist(base / config["watchlist_csv"])

    ranked = compute_candidates(watch, config)
    picks = size_positions(ranked, config)

    export_for_sbi(base, picks, config)
    export_report(base, picks, config)

    print(f"Generated: {base / config['output_orders_csv']}")
    print(f"Generated: {base / config['output_report_md']}")
    print(f"Picks: {len(picks)}")


if __name__ == "__main__":
    main()
