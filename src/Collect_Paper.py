#!/usr/bin/env python3
"""Collect accepted papers from OpenReview API V2 into JSON."""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path
from typing import Any

from common.io_utils import write_json


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def content_value(content: dict[str, Any], key: str) -> str:
    field = content.get(key, "")
    if isinstance(field, dict):
        field = field.get("value", "")
    return clean_text(field)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect accepted papers from OpenReview API V2.")
    parser.add_argument("--venue-id", default="ICLR.cc/2026/Conference")
    parser.add_argument("--output", type=Path, default=Path("Raw_Dataset/iclr2026.json"))
    parser.add_argument("--baseurl", default="https://api2.openreview.net")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        import openreview
    except ModuleNotFoundError as exc:
        raise RuntimeError("Please install openreview-py first: pip install openreview-py") from exc

    client = openreview.api.OpenReviewClient(baseurl=args.baseurl)
    notes = client.get_all_notes(content={"venueid": args.venue_id}, sort="number:asc")
    records = []
    for note in notes:
        content = getattr(note, "content", {}) or {}
        title = content_value(content, "title")
        if not title:
            continue
        records.append(
            {
                "id": note.id,
                "title": title,
                "abstract": content_value(content, "abstract"),
            }
        )
    write_json(args.output, records)
    logging.info("Wrote %d papers to %s", len(records), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
