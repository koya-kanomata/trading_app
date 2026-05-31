# Semi-Auto to Full-Auto Ready Trading Stack (WSL)

This folder now includes two layers:
- Strategy layer: candidate selection and sizing from daily market data.
- Execution layer: automated runner, broker adapter, order queue, and audit log.

Current default execution mode is `paper` broker for safe testing.

LINE Messaging API is supported for both scheduled runs and manual runs. Set `LINE_CHANNEL_ACCESS_TOKEN` and `LINE_TO_ID` in your environment before running the scripts.

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

This is the same command you can run manually any time during the day to re-evaluate the latest state after you trade, receive fills, or update CSV files.

Outputs:
- `orders_for_sbi.csv`: candidate orders (manual backup input sheet)
- `daily_report.md`: summary report
- `order_queue.csv`: queued orders from the paper broker
- `audit_log.csv`: operation history and safety events

### Manual Execution Steps

Use this when you want to run the system on demand instead of waiting for the morning batch.

```bash
cd /home/kanomata/develop/trading_app
source .venv/bin/activate
python auto_trader.py --once
```

Typical use cases:
- after you buy or sell manually on SBI
- after you place downloaded SBI CSV files into `sbi_exports/` or Downloads
- when you want to re-check BUY/SELL recommendations immediately

### Quick Manual Input (When SBI CSV Is Unavailable)

If you cannot export SBI CSV, use `manual_trades.csv` and run `manual_sync.py`.

1. Open `manual_trades.csv` and add rows.
2. Fill columns:
	- `trade_id`: optional (auto-generated if blank)
	- `trade_date`: optional (`YYYY-MM-DD`, defaults to today if blank)
	- `code`: 4-digit stock code
	- `name`: optional but recommended
	- `side`: `BUY` or `SELL`
	- `qty`: shares
	- `price`: executed price
	- `realized_pnl_jpy`: optional (use `0` for BUY)
3. Run:

```bash
cd /home/kanomata/develop/trading_app
source .venv/bin/activate
python manual_sync.py
```

This updates `fills.csv` and `positions.csv` automatically.

Notes:
- Processed `trade_id` values are tracked in `manual_applied_ids.csv` to prevent duplicate imports.
- If you leave `trade_id` blank, a deterministic `AUTO-...` ID is generated from trade fields.

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

## 9) Which Script/File To Use (Operations Quick Guide)

Use this section as a daily checklist.

- `auto_trader.py` (main runner)
	- Purpose: production batch run.
	- When: scheduled by cron each weekday morning, or manual one-off run.
	- What it does: imports SBI CSVs, generates BUY candidates, evaluates SELL signals for OPEN positions, writes outputs/logs.

- `run_daily.sh` (cron entry point)
	- Purpose: stable shell entry for scheduler.
	- When: called by cron.
	- What it does: activates venv, runs importer, runs `auto_trader.py --once`.

- `semi_auto.py` (strategy logic module)
	- Purpose: shared strategy/feature/scoring logic.
	- When: mostly called from `auto_trader.py`.
	- Note: standalone `main()` is a helper path; day-to-day operations should use `auto_trader.py`.

- `sbi_importer.py`
	- Purpose: normalize exported SBI position/fill CSVs into internal files.
	- When: manual import tests or invoked by `run_daily.sh`/`auto_trader.py`.

- `orders_for_sbi.csv` (manual order sheet)
	- Purpose: action list for manual order placement in SBI.
	- When: after each batch run.
	- How to read:
		- `side=BUY`: new entry candidates.
		- `side=SELL`: exit signals for existing OPEN positions.

- `daily_report.md`
	- Purpose: rationale/summary.
	- When: before sending orders.
	- Contains: `BUY Candidates` and `SELL Signals` sections.

- `audit_log.csv` / `cron.log`
	- Purpose: execution proof and troubleshooting.
	- When: to answer "Did it run today?" and to diagnose failures.


- LINE Messaging API
	- Purpose: send a completion or failure message for both batch and manual runs.
	- When: every `auto_trader.py --once` run and every daemon cycle.
	- Setup: export `LINE_CHANNEL_ACCESS_TOKEN` and `LINE_TO_ID` in your shell or profile before running.
	- Message contents: run status, BUY/SELL counts, and a short list of symbols.

### Daily Workflow (Recommended)

1. Wait for scheduled run (07:45 JST on weekdays).
2. Check `audit_log.csv` or `cron.log` to confirm completion.
3. Open `orders_for_sbi.csv`.
4. Place `SELL` rows first (risk reduction), then `BUY` rows.
5. Confirm reasons in `daily_report.md`.
6. Ensure latest SBI exports are available so next cycle can sync positions/fills.

Note: current default operation is batch-based (not real-time). Intraday price shocks can happen after 07:45 output; always use protective stop rules in broker orders.

## 10) Web Dashboard (Spring Boot)

If CLI/CSV operation feels hard, use the web dashboard:

- Path: `reco-web/`
- Shows daily recommendations from `orders_for_sbi.csv`
- Displays BUY/SELL tables with code, qty, limit, stop
- Supports manual run button (`auto_trader.py --once`)
- Runs daily by scheduler at 07:45 JST

### Start

```bash
cd /home/kanomata/develop/trading_app/reco-web
./mvnw spring-boot:run
```

If `mvnw` does not exist, use installed Maven:

```bash
cd /home/kanomata/develop/trading_app/reco-web
mvn spring-boot:run
```

Open:

- `http://localhost:8000`

Settings are in:

- `reco-web/src/main/resources/application.yml`
