#!/usr/bin/env python3
"""Import local oral-medicine DOCX notes into YuReader's ignored data area."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from yureader.oral_focus import write_dataset  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Directory containing the 12 source DOCX files")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "oral-focus" / "content.json")
    args = parser.parse_args()
    payload = write_dataset(args.source, args.output)
    print(json.dumps({"output": str(args.output.resolve()), **payload["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
