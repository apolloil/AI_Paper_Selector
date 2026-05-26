#!/usr/bin/env python3
"""Stage 1 filter: create filtered JSON from rating JSONL."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from common.io_utils import read_jsonl, write_json


def setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_path, encoding="utf-8")],
        force=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 1 filter: keep papers whose score >= threshold.")
    parser.add_argument("--results", type=Path, default=Path("Select_Results/Example_Project/Select_Results/Select1_Eval/stage1_results.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("Select_Results/Example_Project/Select_Results/Select1_Filter/stage1_filtered.json"))
    parser.add_argument("--log-file", type=Path, default=Path("Select_Results/Example_Project/Select_Results/Select1_Filter/run.log"))
    parser.add_argument("--threshold", type=int, default=8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging(args.log_file)
    rows = read_jsonl(args.results) if args.results.exists() else []
    filtered = [
        row
        for row in rows
        if isinstance(row.get("suitability_score"), int) and row["suitability_score"] >= args.threshold
    ]
    filtered.sort(key=lambda row: (row.get("suitability_score", 0), row.get("title", "")), reverse=True)
    write_json(args.output, filtered)
    logging.info("Filtered input=%d threshold=%d output=%d path=%s", len(rows), args.threshold, len(filtered), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
