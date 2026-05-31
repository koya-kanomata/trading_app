from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path

import pandas as pd


POSITIONS_COLUMNS = ["code", "name", "qty", "entry_price", "entry_date", "status"]
FILLS_COLUMNS = ["fill_date", "code", "side", "qty", "price", "realized_pnl_jpy"]
APPLIED_COLUMNS = ["trade_id", "applied_at"]


def ensure_csv(path: Path, columns: list[str]) -> None:
    if path.exists():
        return
    pd.DataFrame(columns=columns).to_csv(path, index=False)


def to_code(raw: object) -> str:
    s = str(raw).strip()
    if s.endswith(".0"):
        s = s[:-2]
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits.zfill(4)


def normalize_manual_trades(df: pd.DataFrame) -> pd.DataFrame:
    required = ["code", "side", "qty", "price"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"manual_trades.csv missing columns: {', '.join(missing)}")

    out = df.copy()
    if "trade_date" not in out.columns:
        out["trade_date"] = ""
    if "name" not in out.columns:
        out["name"] = ""
    if "realized_pnl_jpy" not in out.columns:
        out["realized_pnl_jpy"] = 0

    if "trade_id" not in out.columns:
        out["trade_id"] = ""
    out["trade_id"] = out["trade_id"].astype(str).str.strip()

    trade_date_raw = out["trade_date"].astype(str).str.strip()
    trade_date_raw = trade_date_raw.replace({"": pd.NA, "nan": pd.NA, "NaN": pd.NA})
    out["trade_date"] = pd.to_datetime(trade_date_raw, errors="coerce")
    today_str = datetime.now().date().isoformat()
    out["trade_date"] = out["trade_date"].dt.date.astype(str).replace({"NaT": today_str})
    out["code"] = out["code"].map(to_code)
    out["name"] = out["name"].astype(str).fillna("")
    out["side"] = out["side"].astype(str).str.upper().str.strip()
    out["qty"] = pd.to_numeric(out["qty"], errors="coerce").fillna(0).astype(int)
    out["price"] = pd.to_numeric(out["price"], errors="coerce")
    out["realized_pnl_jpy"] = pd.to_numeric(out["realized_pnl_jpy"], errors="coerce").fillna(0)

    out = out[
        (out["trade_date"] != "NaT")
        & (out["code"] != "")
        & (out["side"].isin(["BUY", "SELL"]))
        & (out["qty"] > 0)
        & (out["price"] > 0)
    ].copy()

    # Generate a deterministic trade_id when omitted to keep re-runs idempotent.
    missing_id_mask = out["trade_id"] == ""
    if missing_id_mask.any():
        for idx in out[missing_id_mask].index:
            key = "|".join(
                [
                    str(out.at[idx, "trade_date"]),
                    str(out.at[idx, "code"]),
                    str(out.at[idx, "side"]),
                    str(int(out.at[idx, "qty"])),
                    f"{float(out.at[idx, 'price']):.4f}",
                    str(out.at[idx, "name"]),
                ]
            )
            digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
            out.at[idx, "trade_id"] = f"AUTO-{digest}"

    dup = out["trade_id"].duplicated(keep=False)
    if dup.any():
        ids = ", ".join(sorted(out.loc[dup, "trade_id"].unique().tolist()))
        raise ValueError(f"Duplicate trade_id in manual_trades.csv: {ids}")

    return out


def apply_buy(positions: pd.DataFrame, code: str, name: str, qty: int, price: float, trade_date: str) -> pd.DataFrame:
    mask = (positions["code"].astype(str).str.zfill(4) == code) & (
        positions["status"].astype(str).str.upper() == "OPEN"
    )
    if mask.any():
        idx = positions[mask].index[0]
        old_qty = int(pd.to_numeric(positions.at[idx, "qty"], errors="coerce") or 0)
        old_price = float(pd.to_numeric(positions.at[idx, "entry_price"], errors="coerce") or 0)
        old_date = str(positions.at[idx, "entry_date"]) if str(positions.at[idx, "entry_date"]) else trade_date

        new_qty = old_qty + qty
        new_price = ((old_qty * old_price) + (qty * price)) / new_qty if new_qty > 0 else price
        positions.at[idx, "qty"] = new_qty
        positions.at[idx, "entry_price"] = round(new_price, 4)
        positions.at[idx, "entry_date"] = min(old_date, trade_date)
        if name:
            positions.at[idx, "name"] = name
        return positions

    positions = positions[positions["code"].astype(str).str.zfill(4) != code].copy()
    positions = pd.concat(
        [
            positions,
            pd.DataFrame(
                [
                    {
                        "code": code,
                        "name": name,
                        "qty": qty,
                        "entry_price": price,
                        "entry_date": trade_date,
                        "status": "OPEN",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    return positions


def apply_sell(positions: pd.DataFrame, code: str, qty: int) -> tuple[pd.DataFrame, str | None]:
    mask = (positions["code"].astype(str).str.zfill(4) == code) & (
        positions["status"].astype(str).str.upper() == "OPEN"
    )
    if not mask.any():
        return positions, f"SELL without OPEN position: {code}"

    idx = positions[mask].index[0]
    old_qty = int(pd.to_numeric(positions.at[idx, "qty"], errors="coerce") or 0)
    if qty < old_qty:
        positions.at[idx, "qty"] = old_qty - qty
        return positions, None

    positions.at[idx, "status"] = "CLOSED"
    positions.at[idx, "qty"] = old_qty
    if qty > old_qty:
        return positions, f"SELL qty exceeds OPEN qty for {code}: sell={qty} open={old_qty}"
    return positions, None


def main() -> None:
    base = Path(__file__).resolve().parent

    manual_path = base / "manual_trades.csv"
    applied_path = base / "manual_applied_ids.csv"
    positions_path = base / "positions.csv"
    fills_path = base / "fills.csv"

    ensure_csv(manual_path, ["trade_id", "trade_date", "code", "name", "side", "qty", "price", "realized_pnl_jpy"])
    ensure_csv(applied_path, APPLIED_COLUMNS)
    ensure_csv(positions_path, POSITIONS_COLUMNS)
    ensure_csv(fills_path, FILLS_COLUMNS)

    manual_df = pd.read_csv(manual_path, dtype={"code": str})
    if manual_df.empty:
        print("manual_trades.csv is empty. Add rows and run again.")
        return

    manual_df = normalize_manual_trades(manual_df)
    if manual_df.empty:
        print("No valid rows in manual_trades.csv.")
        return

    applied_df = pd.read_csv(applied_path, dtype={"trade_id": str})
    applied_ids = set(applied_df["trade_id"].astype(str).str.strip().tolist()) if not applied_df.empty else set()

    new_rows = manual_df[~manual_df["trade_id"].isin(applied_ids)].copy()
    if new_rows.empty:
        print("No new trades to apply.")
        return

    positions = pd.read_csv(positions_path, dtype={"code": str})
    if positions.empty:
        positions = pd.DataFrame(columns=POSITIONS_COLUMNS)
    else:
        for col in POSITIONS_COLUMNS:
            if col not in positions.columns:
                positions[col] = ""
        positions = positions[POSITIONS_COLUMNS].copy()

    fills = pd.read_csv(fills_path, dtype={"code": str})
    if fills.empty:
        fills = pd.DataFrame(columns=FILLS_COLUMNS)
    else:
        for col in FILLS_COLUMNS:
            if col not in fills.columns:
                fills[col] = ""
        fills = fills[FILLS_COLUMNS].copy()

    warnings: list[str] = []
    applied_now: list[dict[str, str]] = []

    new_rows = new_rows.sort_values(["trade_date", "trade_id"])
    for _, row in new_rows.iterrows():
        code = str(row["code"]).zfill(4)
        name = str(row.get("name", ""))
        side = str(row["side"]).upper()
        qty = int(row["qty"])
        price = float(row["price"])
        trade_date = str(row["trade_date"])
        pnl = float(row.get("realized_pnl_jpy", 0))

        fills = pd.concat(
            [
                fills,
                pd.DataFrame(
                    [
                        {
                            "fill_date": trade_date,
                            "code": code,
                            "side": side,
                            "qty": qty,
                            "price": price,
                            "realized_pnl_jpy": pnl,
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )

        if side == "BUY":
            positions = apply_buy(positions, code, name, qty, price, trade_date)
        else:
            positions, warn = apply_sell(positions, code, qty)
            if warn:
                warnings.append(warn)

        applied_now.append(
            {
                "trade_id": str(row["trade_id"]),
                "applied_at": datetime.now().isoformat(timespec="seconds"),
            }
        )

    fills = fills.drop_duplicates().copy()
    fills.to_csv(fills_path, index=False)

    positions["code"] = positions["code"].astype(str).str.zfill(4)
    positions.to_csv(positions_path, index=False)

    applied_df = pd.concat([applied_df, pd.DataFrame(applied_now)], ignore_index=True)
    applied_df = applied_df.drop_duplicates(subset=["trade_id"], keep="last")
    applied_df.to_csv(applied_path, index=False)

    print(f"Applied {len(applied_now)} trade(s).")
    if warnings:
        print("Warnings:")
        for w in warnings:
            print(f"- {w}")


if __name__ == "__main__":
    main()
