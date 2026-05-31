#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

source .venv/bin/activate
python sbi_importer.py --base-dir "$SCRIPT_DIR" --import-dir sbi_exports
python auto_trader.py --once
