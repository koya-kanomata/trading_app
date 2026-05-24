# Semi-Auto to Full-Auto Ready Trading Stack (WSL)

This folder now includes two layers:
- Strategy layer: candidate selection and sizing from daily market data.
- Execution layer: automated runner, broker adapter, order queue, and audit log.

Current default execution mode is `paper` broker for safe testing.

## 1) Setup

```bash
cd ~/trading_semi_auto
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 2) One-Off Daily Run

```bash
python auto_trader.py --once
```

Outputs:
- `orders_for_sbi.csv`: candidate orders (manual backup input sheet)
- `daily_report.md`: summary report
- `order_queue.csv`: queued orders from the paper broker
- `audit_log.csv`: operation history and safety events

## 3) Daemon Mode (WSL Always-On)

```bash
python auto_trader.py
```

The daemon checks local JST time and runs once on each business day at `run_time` in `config.json`.

## 4) Data Files You Maintain

- `positions.csv`: current open positions
- `fills.csv`: realized executions and realized PnL

If these are empty, the runner still works and will initialize them.

### SBI Export Auto-Import (Next Stage)

Put exported SBI CSV files into `sbi_exports/` and run:

```bash
python sbi_importer.py --base-dir ~/trading_semi_auto --import-dir sbi_exports
```

Auto-detected examples:
- Position files: `*pos*.csv`, `*保有*.csv`
- Fill/history files: `*fill*.csv`, `*約定*.csv`, `*履歴*.csv`

`auto_trader.py` also performs this sync at the start of each cycle.

### Fully Automated Step 1 (No Manual Copy)

`auto_trader.py` can automatically collect CSV files from Windows Downloads and copy them into `sbi_exports/` before import.

Default source path:
- `/mnt/c/Users/kanomata/Downloads`

Configure in `config.json` using `sbi_collect`:
- `enabled`
- `source_dir`
- `patterns`
- `max_files`

## 5) Safety Controls

- Per-trade risk: `risk_per_trade` (0.7%)
- Daily stop: `daily_loss_limit_jpy` (20000)
- Max new positions per day: 3
- Kill switch file: create `KILL_SWITCH` in this folder to halt new orders

## 6) Broker Adapter

- `broker = "paper"` (default): orders are queued only.
- `broker = "sbi"`: placeholder adapter is present and can be wired when official API specs are available.

Credentials are read from environment variables only (never hard-code secrets).

## 7) Recommended WSL Cron

```bash
chmod +x run_daily.sh
crontab -e
```

Add this line:

```bash
45 7 * * 1-5 /home/kanomata/trading_semi_auto/run_daily.sh >> /home/kanomata/trading_semi_auto/cron.log 2>&1
```

## 8) Manual SBI Backup Flow

If broker API is not connected yet, use `orders_for_sbi.csv`:
1. BUY by `code`
2. Quantity from `qty`
3. Limit price from `entry_limit`
4. Reverse stop from `stop_loss`
5. TP target from `take_profit`
