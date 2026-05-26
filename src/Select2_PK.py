#!/usr/bin/env python3
"""Stage 2 PK: tournament-style final paper selection."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from common.io_utils import read_json, write_json
from common.llm_utils import call_llm_json, create_openai_client, retry_call
from common.prompts import STAGE2_PROMPT


def setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_path, encoding="utf-8")],
        force=True,
    )


def chunks(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def compact_paper(paper: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": paper["id"],
        "title": paper["title"],
        "abstract": paper.get("abstract", ""),
    }


def validate_selection(
    response: Any,
    batch: list[dict[str, Any]],
    selection_min: int,
    selection_max: int,
) -> dict[str, list[dict[str, str]]]:
    if not isinstance(response, dict):
        raise ValueError("Stage 2 response must be a JSON object")
    selected_raw = response.get("selected_papers")
    rejected_raw = response.get("rejected_papers")
    if not isinstance(selected_raw, list) or not isinstance(rejected_raw, list):
        raise ValueError("Stage 2 response must contain selected_papers and rejected_papers")
    batch_ids = {paper["id"] for paper in batch}
    selected = []
    selected_ids = set()
    for item in selected_raw:
        if not isinstance(item, dict):
            continue
        paper_id = str(item.get("id", "")).strip()
        if paper_id in batch_ids and paper_id not in selected_ids:
            selected_ids.add(paper_id)
            selected.append({"id": paper_id, "selection_reason": str(item.get("selection_reason", "")).strip()})
    if not selection_min <= len(selected) <= selection_max:
        raise ValueError(f"Selected {len(selected)} papers, expected between {selection_min} and {selection_max}")
    rejected = []
    for paper in batch:
        if paper["id"] in selected_ids:
            continue
        reason = ""
        for item in rejected_raw:
            if isinstance(item, dict) and str(item.get("id", "")).strip() == paper["id"]:
                reason = str(item.get("rejection_reason", "")).strip()
                break
        rejected.append({"id": paper["id"], "rejection_reason": reason or "Not selected in this batch."})
    return {"selected_papers": selected, "rejected_papers": rejected}


def human_readable_selection(
    parsed: dict[str, list[dict[str, str]]],
    by_id: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, str]]]:
    selected = [
        {
            "title": by_id[item["id"]]["title"],
            "selection_reason": item["selection_reason"],
        }
        for item in parsed["selected_papers"]
    ]
    rejected = [
        {
            "title": by_id[item["id"]]["title"],
            "rejection_reason": item["rejection_reason"],
        }
        for item in parsed["rejected_papers"]
    ]
    return {"selected_papers": selected, "rejected_papers": rejected}


def build_selected_candidates(
    parsed: dict[str, list[dict[str, str]]],
    by_id: dict[str, dict[str, Any]],
    round_index: int,
) -> list[dict[str, Any]]:
    selected_candidates = []
    for item in parsed["selected_papers"]:
        paper = compact_paper(by_id[item["id"]])
        paper["selection_reason"] = item["selection_reason"]
        paper["selection_round"] = round_index
        selected_candidates.append(paper)
    return selected_candidates


def refresh_round_output_stats(round_output: dict[str, Any]) -> None:
    round_output["completed_batches"] = len(round_output.get("batch_decisions", []))
    round_output["output_count"] = len(round_output.get("selected_candidates", []))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 2 PK: tournament-style final selection.")
    parser.add_argument("--candidates", type=Path, default=Path("Select_Results/Example_Project/Select_Results/Select1_Filter/stage1_filtered.json"))
    parser.add_argument("--profile", type=Path, default=Path("Select_Results/Example_Project/Research_Profile/Select2_Standard.md"))
    parser.add_argument("--output-dir", type=Path, default=Path("Select_Results/Example_Project/Select_Results/Select2_PK1"))
    parser.add_argument("--final-output", type=Path, default=Path("Select_Results/Example_Project/Select_Results/Select2_PK1/final_output.json"))
    parser.add_argument("--log-file", type=Path, default=Path("Select_Results/Example_Project/Select_Results/Select2_PK1/run.log"))
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--batch-size", type=int, default=15)
    parser.add_argument("--selection-target", type=int, default=2)
    parser.add_argument("--max-final", type=int, default=25)
    parser.add_argument("--max-rounds", type=int, default=None)
    parser.add_argument("--start-round", type=int, default=1)
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--retry-initial-wait", type=float, default=2.0)
    parser.add_argument("--retry-max-wait", type=float, default=60.0)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=5000)
    parser.add_argument("--json-mode", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging(args.log_file)
    profile = args.profile.read_text(encoding="utf-8")
    candidates_data = read_json(args.candidates)
    if isinstance(candidates_data, dict) and isinstance(candidates_data.get("selected_candidates"), list):
        candidates = candidates_data["selected_candidates"]
    elif isinstance(candidates_data, list):
        candidates = candidates_data
    else:
        raise ValueError(f"{args.candidates} must contain a JSON list or an object with selected_candidates")
    client = create_openai_client()
    current = list(candidates)
    round_index = args.start_round
    rounds_completed = 0

    while len(current) > args.max_final:
        batches = chunks(current, args.batch_size)
        by_id = {paper["id"]: paper for paper in current}
        round_output_path = args.output_dir / f"round{round_index}_output.json"
        if round_output_path.exists():
            round_output = read_json(round_output_path)
            if not isinstance(round_output, dict):
                raise ValueError(f"{round_output_path} must contain a JSON object")
            round_output.setdefault("batch_decisions", [])
            round_output.setdefault("selected_candidates", [])
        else:
            round_output = {
                "round": round_index,
                "input_count": len(current),
                "batch_size": args.batch_size,
                "total_batches": len(batches),
                "batch_decisions": [],
                "selected_candidates": [],
            }
            write_json(round_output_path, round_output)
        completed_batches = {int(item["batch"]) for item in round_output["batch_decisions"]}
        logging.info("Stage 2 round=%d candidates=%d batches=%d", round_index, len(current), len(batches))
        for batch_index, batch in enumerate(batches, start=1):
            if batch_index in completed_batches:
                logging.info("Stage 2 round=%d batch=%d/%d skipped existing result", round_index, batch_index, len(batches))
                continue
            if len(batch) <= 2:
                selected_candidates = [compact_paper(paper) | {"selection_reason": "Small carry-over batch.", "selection_round": round_index} for paper in batch]
                round_output["selected_candidates"].extend(selected_candidates)
                round_output["batch_decisions"].append(
                    {
                        "batch": batch_index,
                        "selection_min": len(batch),
                        "selection_max": len(batch),
                        "selected_papers": [{"title": item["title"], "selection_reason": item["selection_reason"]} for item in selected_candidates],
                        "rejected_papers": [],
                    }
                )
                refresh_round_output_stats(round_output)
                write_json(round_output_path, round_output)
                continue
            target_count = min(args.selection_target, len(batch))
            selection_min = max(1, target_count - 1)
            selection_max = min(len(batch), target_count + 1)
            prompt = STAGE2_PROMPT.format(
                research_profile=profile,
                selection_min=selection_min,
                selection_max=selection_max,
                batch_papers=json.dumps([compact_paper(p) for p in batch], ensure_ascii=False, indent=2),
            )
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
                label=f"stage2 round={round_index} batch={batch_index}",
                max_retries=args.max_retries,
                initial_wait=args.retry_initial_wait,
                max_wait=args.retry_max_wait,
            )
            parsed = validate_selection(response, batch, selection_min, selection_max)
            selected_candidates = build_selected_candidates(parsed, by_id, round_index)
            round_output["batch_decisions"].append(
                {
                    "batch": batch_index,
                    "selection_min": selection_min,
                    "selection_max": selection_max,
                    **human_readable_selection(parsed, by_id),
                }
            )
            round_output["selected_candidates"].extend(selected_candidates)
            refresh_round_output_stats(round_output)
            write_json(round_output_path, round_output)
            logging.info("Stage 2 round=%d batch=%d/%d selected_so_far=%d elapsed=%.1fs", round_index, batch_index, len(batches), len(round_output["selected_candidates"]), time.monotonic() - started_at)
            time.sleep(args.sleep_seconds)
        current = round_output["selected_candidates"]
        refresh_round_output_stats(round_output)
        write_json(round_output_path, round_output)
        rounds_completed += 1
        if args.max_rounds is not None and rounds_completed >= args.max_rounds:
            logging.info("Stage 2 stopped after max_rounds=%d: selected=%d output=%s", args.max_rounds, len(current), round_output_path)
            return 0
        round_index += 1

    write_json(args.final_output, current[: args.max_final])
    logging.info("Stage 2 complete: final=%d path=%s", min(len(current), args.max_final), args.final_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
