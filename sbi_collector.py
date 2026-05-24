from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Dict, List


def latest_files(src: Path, patterns: List[str], max_files: int) -> List[Path]:
    files: List[Path] = []
    for pat in patterns:
        files.extend(src.glob(pat))
    files = [f for f in files if f.is_file()]
    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

    seen = set()
    unique: List[Path] = []
    for f in files:
        key = str(f.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(f)
        if len(unique) >= max_files:
            break
    return unique


def collect_exports(download_dir: Path, target_dir: Path, patterns: List[str], max_files: int = 20) -> Dict[str, int]:
    target_dir.mkdir(parents=True, exist_ok=True)
    picked = latest_files(download_dir, patterns, max_files=max_files)

    copied = 0
    skipped = 0
    for src in picked:
        dst = target_dir / src.name
        if dst.exists() and dst.stat().st_size == src.stat().st_size and int(dst.stat().st_mtime) >= int(src.stat().st_mtime):
            skipped += 1
            continue
        shutil.copy2(src, dst)
        copied += 1

    return {"found": len(picked), "copied": copied, "skipped": skipped}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect SBI CSV exports from a source folder")
    parser.add_argument("--source", required=True, help="source folder (e.g. /mnt/c/Users/<name>/Downloads)")
    parser.add_argument("--target", default="sbi_exports", help="target folder")
    parser.add_argument(
        "--patterns",
        nargs="*",
        default=["*SBI*.csv", "*保有*.csv", "*約定*.csv", "*履歴*.csv", "*.csv"],
        help="glob patterns to search",
    )
    parser.add_argument("--max-files", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = Path(args.source).expanduser().resolve()
    target = Path(args.target).expanduser().resolve()

    if not source.exists():
        print(f"Source not found: {source}")
        return

    result = collect_exports(source, target, patterns=list(args.patterns), max_files=int(args.max_files))
    print(f"Collect result: found={result['found']} copied={result['copied']} skipped={result['skipped']}")


if __name__ == "__main__":
    main()
