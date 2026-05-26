#!/usr/bin/env python3
"""Stage 1 eval: serial LLM scoring with JSONL checkpoint resume."""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any

from common.io_utils import append_jsonl, read_jsonl, read_papers
from common.llm_utils import call_llm_json, create_openai_client, retry_call
from common.prompts import STAGE1_PROMPT


def setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_path, encoding="utf-8")],
        force=True,
    )


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_paper(record: dict[str, Any]) -> dict[str, str]:
    paper_id = clean_text(record.get("id"))
    title = clean_text(record.get("title"))
    abstract = clean_text(record.get("abstract"))
    if not paper_id or not title:
        raise ValueError(f"Paper is missing id or title: {record!r}")
    return {"id": paper_id, "title": title, "abstract": abstract}


def chunks(items: list[dict[str, str]], size: int) -> list[list[dict[str, str]]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def processed_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {clean_text(row.get("id")) for row in read_jsonl(path) if clean_text(row.get("id"))}


def validate_rating(item: dict[str, Any]) -> dict[str, Any]:
    required = ["id", "application_domain", "method_core", "transferability_analysis", "suitability_score"]
    missing = [key for key in required if key not in item]
    if missing:
        raise ValueError(f"Rating item missing keys: {missing}")
    score = item["suitability_score"]
    if isinstance(score, str):
        match = re.search(r"\d+", score)
        if not match:
            raise ValueError(f"Invalid suitability_score: {score!r}")
        score = int(match.group(0))
    if not isinstance(score, int):
        raise ValueError(f"Invalid suitability_score type: {type(score).__name__}")
    return {
        "id": clean_text(item["id"]),
        "application_domain": clean_text(item["application_domain"]),
        "method_core": clean_text(item["method_core"]),
        "transferability_analysis": clean_text(item["transferability_analysis"]),
        "suitability_score": max(1, min(10, score)),
    }


def validate_batch_response(response: Any, batch: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    if not isinstance(response, dict) or not isinstance(response.get("results"), list):
        raise ValueError("Stage 1 response must be an object with a results list")
    expected = {paper["id"] for paper in batch}
    by_id: dict[str, dict[str, Any]] = {}
    for item in response["results"]:
        if not isinstance(item, dict):
            continue
        rating = validate_rating(item)
        if rating["id"] in expected:
            by_id[rating["id"]] = rating
    missing = expected - set(by_id)
    if missing:
        raise ValueError(f"Stage 1 response missing ids: {sorted(missing)}")
    return by_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 1: evaluate papers with a serial LLM workflow.")
    parser.add_argument("--papers", type=Path, default=Path("Raw_Dataset/iclr2026.json"))
    parser.add_argument("--profile", type=Path, default=Path("Select_Results/Example_Project/Research_Profile/Select1_Standard.md"))
    parser.add_argument("--output", type=Path, default=Path("Select_Results/Example_Project/Select_Results/Select1_Eval/stage1_results.jsonl"))
    parser.add_argument("--log-file", type=Path, default=Path("Select_Results/Example_Project/Select_Results/Select1_Eval/run.log"))
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--retry-initial-wait", type=float, default=2.0)
    parser.add_argument("--retry-max-wait", type=float, default=60.0)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=6000)
    parser.add_argument("--json-mode", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--restart", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging(args.log_file)
    if args.restart and args.output.exists():
        args.output.unlink()

    research_profile = args.profile.read_text(encoding="utf-8")
    papers = [normalize_paper(paper) for paper in read_papers(args.papers)]
    if args.limit is not None:
        papers = papers[: args.limit]
    done = processed_ids(args.output)
    pending = [paper for paper in papers if paper["id"] not in done]
    batches = chunks(pending, max(1, args.batch_size))
    client = create_openai_client()

    logging.info("Loaded=%d processed=%d pending=%d batch_size=%d model=%s", len(papers), len(done), len(pending), args.batch_size, args.model)
    for batch_index, batch in enumerate(batches, start=1):
        batch = [paper for paper in batch if paper["id"] not in done]
        if not batch:
            continue
        logging.info("Stage 1 batch start: %d/%d size=%d ids=%s", batch_index, len(batches), len(batch), ",".join(p["id"] for p in batch))
        prompt = STAGE1_PROMPT.format(research_profile=research_profile, papers_json=json.dumps(batch, ensure_ascii=False, indent=2))
        try:
            started_at = time.monotonic()
            response = retry_call(
                lambda: call_llm_json(
                    client,
                    model=args.model,
                    prompt=prompt,
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                    json_mode=args.json_mode,
                ),
                label=f"stage1 batch={batch_index}",
                max_retries=args.max_retries,
                initial_wait=args.retry_initial_wait,
                max_wait=args.retry_max_wait,
            )
            ratings = validate_batch_response(response, batch)
            for paper in batch:
                append_jsonl(args.output, {**paper, **ratings[paper["id"]]})
                done.add(paper["id"])
            logging.info("Stage 1 batch done: %d/%d processed=%d elapsed=%.1fs", batch_index, len(batches), len(done), time.monotonic() - started_at)
        except Exception:
            logging.exception("Stage 1 batch failed and skipped: batch=%d ids=%s", batch_index, ",".join(p["id"] for p in batch))
            continue
        time.sleep(args.sleep_seconds)
    logging.info("Stage 1 rating complete: %s", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
