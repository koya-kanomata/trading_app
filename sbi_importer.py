from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd


ENCODINGS = ["utf-8-sig", "cp932", "shift_jis", "utf-8"]


def read_csv_any(path: Path) -> pd.DataFrame:
    last_error: Exception | None = None
    for enc in ENCODINGS:
        try:
            return pd.read_csv(path, encoding=enc)
        except Exception as e:  # noqa: BLE001
            last_error = e
    if last_error:
        raise last_error
    raise ValueError(f"Unable to read CSV: {path}")


def norm_col(name: str) -> str:
    return (
        str(name)
        .strip()
        .lower()
        .replace(" ", "")
        .replace("　", "")
        .replace("_", "")
        .replace("-", "")
    )


def find_col(df: pd.DataFrame, aliases: Iterable[str]) -> Optional[str]:
    alias_set = {norm_col(a) for a in aliases}
    for c in df.columns:
        if norm_col(c) in alias_set:
            return c
    return None


def to_code(val: object) -> str:
    s = str(val).strip()
    if s.endswith(".0"):
        s = s[:-2]
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return ""
    return digits.zfill(4)


def to_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.replace(",", "", regex=False), errors="coerce")


def normalize_positions(df: pd.DataFrame) -> pd.DataFrame:
    code_col = find_col(df, ["code", "銘柄コード", "コード", "銘柄番号"])
    name_col = find_col(df, ["name", "銘柄", "銘柄名"])
    qty_col = find_col(df, ["qty", "数量", "保有数量", "株数", "保有株数"])
    entry_col = find_col(df, ["entry_price", "取得単価", "平均取得単価", "買付単価"])
    date_col = find_col(df, ["entry_date", "取得日", "約定日", "買付日"])

    if not (code_col and qty_col):
        raise ValueError("positions CSV mapping failed: code/qty column not found")

    out = pd.DataFrame()
    out["code"] = df[code_col].map(to_code)
    out["name"] = df[name_col].astype(str).fillna("") if name_col else ""
    out["qty"] = to_num(df[qty_col]).fillna(0).astype(int)
    out["entry_price"] = to_num(df[entry_col]).fillna(0.0) if entry_col else 0.0
    out["entry_date"] = df[date_col].astype(str).fillna("") if date_col else ""
    out["status"] = "OPEN"

    out = out[(out["code"] != "") & (out["qty"] > 0)].copy()
    out = out.drop_duplicates(subset=["code"], keep="last")
    return out


def normalize_side(val: object) -> str:
    s = str(val)
    if any(k in s for k in ["買", "BUY", "buy"]):
        return "BUY"
    if any(k in s for k in ["売", "SELL", "sell"]):
        return "SELL"
    return ""


def normalize_fills(df: pd.DataFrame) -> pd.DataFrame:
    date_col = find_col(df, ["fill_date", "約定日", "受渡日", "取引日", "日付"])
    code_col = find_col(df, ["code", "銘柄コード", "コード", "銘柄番号"])
    side_col = find_col(df, ["side", "売買", "取引", "区分"])
    qty_col = find_col(df, ["qty", "数量", "約定数量", "株数"])
    price_col = find_col(df, ["price", "約定単価", "単価", "約定価格", "価格"])
    pnl_col = find_col(df, ["realized_pnl_jpy", "実現損益", "損益", "譲渡損益"])

    if not (date_col and code_col and side_col and qty_col and price_col):
        raise ValueError("fills CSV mapping failed: required columns not found")

    out = pd.DataFrame()
    out["fill_date"] = pd.to_datetime(df[date_col], errors="coerce").dt.date.astype(str)
    out["code"] = df[code_col].map(to_code)
    out["side"] = df[side_col].map(normalize_side)
    out["qty"] = to_num(df[qty_col]).fillna(0).astype(int)
    out["price"] = to_num(df[price_col]).fillna(0.0)
    if pnl_col:
        out["realized_pnl_jpy"] = to_num(df[pnl_col]).fillna(0.0)
    else:
        out["realized_pnl_jpy"] = 0.0

    out = out[(out["fill_date"] != "NaT") & (out["code"] != "") & (out["qty"] > 0)].copy()
    return out


def latest_by_patterns(base: Path, patterns: List[str]) -> Optional[Path]:
    cands: List[Path] = []
    for p in patterns:
        cands.extend(list(base.glob(p)))
    if not cands:
        return None
    cands.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return cands[0]


def import_sbi_exports(
    *,
    base_dir: Path,
    import_dir: Path,
    positions_patterns: List[str],
    fills_patterns: List[str],
    positions_out: Path,
    fills_out: Path,
) -> Dict[str, str]:
    result: Dict[str, str] = {}

    pos_src = latest_by_patterns(import_dir, positions_patterns)
    if pos_src:
        pos_df = read_csv_any(pos_src)
        norm_pos = normalize_positions(pos_df)
        norm_pos.to_csv(positions_out, index=False)
        result["positions"] = str(pos_src)

    fill_src = latest_by_patterns(import_dir, fills_patterns)
    if fill_src:
        fill_df = read_csv_any(fill_src)
        norm_fill = normalize_fills(fill_df)
        norm_fill.to_csv(fills_out, index=False)
        result["fills"] = str(fill_src)

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import SBI exported CSV files")
    parser.add_argument("--base-dir", default=".", help="trading folder path")
    parser.add_argument("--import-dir", default="sbi_exports", help="folder containing exported CSV files")
    parser.add_argument("--positions-patterns", nargs="*", default=["*pos*.csv", "*保有*.csv"])
    parser.add_argument("--fills-patterns", nargs="*", default=["*fill*.csv", "*約定*.csv", "*履歴*.csv"])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base = Path(args.base_dir).resolve()
    import_dir = (base / args.import_dir).resolve()
    positions_out = base / "positions.csv"
    fills_out = base / "fills.csv"

    result = import_sbi_exports(
        base_dir=base,
        import_dir=import_dir,
        positions_patterns=args.positions_patterns,
        fills_patterns=args.fills_patterns,
        positions_out=positions_out,
        fills_out=fills_out,
    )

    if not result:
        print("No SBI export files found.")
        return

    for k, v in result.items():
        print(f"Imported {k}: {v}")


if __name__ == "__main__":
    main()
