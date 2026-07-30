#!/usr/bin/env python3
"""
cli.py
Local runner for the OpenAI/Railway meeting-actions pipeline.

Dry-run by default — pass --apply to actually create Zoho tasks.

Usage:
    python3 cli.py <summary_file.txt> [--blake-only] [--apply]
    python3 cli.py "Blake's Weekly Catch-Up_summary.txt" --blake-only
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import pipeline

NOTES_DIR = Path.home() / "Bevco/notes/meeting_notes/weekly"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run meeting-actions extraction locally")
    parser.add_argument("summary_file", help="Path to a *_summary.txt (or name under weekly notes dir)")
    parser.add_argument("--blake-only", action="store_true", help="Only create Blake-owned tasks")
    parser.add_argument("--apply", action="store_true", help="Actually create Zoho tasks (default: dry-run)")
    parser.add_argument("--force", action="store_true",
                        help="Reprocess even if this file is in processed_notes.json (title/dedupe-key checks still apply)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(name)s  %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    path = Path(args.summary_file)
    if not path.exists():
        path = NOTES_DIR / args.summary_file
    if not path.exists():
        print(f"[error] File not found: {args.summary_file}", file=sys.stderr)
        sys.exit(1)

    pipeline.load_local_env()

    result = pipeline.process_summary(
        summary_text=path.read_text(encoding="utf-8"),
        summary_file_name=path.name,
        dry_run=not args.apply,
        blake_only=args.blake_only,
        force=args.force,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
