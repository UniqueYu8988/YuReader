"""Audit a Markdown source for canonical, substituted, and missing 𬌗 terms."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from import_markdown import (
    OCCLUSION_PROFILE,
    SAFE_OCCLUSION_REPLACEMENTS,
    replace_occlusion_alias,
)


def line_excerpt(lines: list[str], line_number: int, start: int, end: int) -> str:
    line = lines[line_number - 1]
    left = max(0, start - 24)
    right = min(len(line), end + 24)
    return line[left:right].strip()


def audit(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    canonical_terms = sorted(
        {
            str(term)
            for group in OCCLUSION_PROFILE["canonical_groups"]
            for term in group["terms"]
        },
        key=lambda term: (-len(term), term),
    )
    canonical_counts = {
        term: text.count(term) for term in canonical_terms if text.count(term)
    }
    aliases = []
    normalized_text = text
    for before, after in SAFE_OCCLUSION_REPLACEMENTS:
        normalized_text, count = replace_occlusion_alias(normalized_text, before, after)
        if count:
            aliases.append({"found": before, "canonical": after, "count": count})

    missing_candidates = []
    normalized_lines = normalized_text.splitlines()
    for rule in OCCLUSION_PROFILE["missing_character_patterns"]:
        pattern = re.compile(str(rule["pattern"]))
        matches = []
        for line_number, line in enumerate(normalized_lines, start=1):
            for match in pattern.finditer(line):
                matches.append(
                    {
                        "line": line_number,
                        "found": match.group(0),
                        "excerpt": line_excerpt(
                            normalized_lines, line_number, match.start(), match.end()
                        ),
                    }
                )
        if matches:
            missing_candidates.append(
                {
                    "rule": rule["id"],
                    "replacement": rule["replacement"],
                    "action": rule["action"],
                    "reason": rule["reason"],
                    "count": len(matches),
                    "matches": matches,
                }
            )

    preserved = {
        word: text.count(word)
        for word in OCCLUSION_PROFILE["confusions"]["preserve_as_written"]
        if text.count(word)
    }
    return {
        "source": str(path.resolve()),
        "character_count": len(text),
        "canonical_occlusion_character_count": text.count("𬌗"),
        "canonical_terms": canonical_counts,
        "substitution_candidates": aliases,
        "missing_character_candidates": missing_candidates,
        "protected_legitimate_words": preserved,
        "summary": {
            "canonical_term_types": len(canonical_counts),
            "substitution_candidate_count": sum(item["count"] for item in aliases),
            "automatic_missing_count": sum(
                item["count"] for item in missing_candidates if item["action"] == "automatic"
            ),
            "detect_only_missing_count": sum(
                item["count"] for item in missing_candidates if item["action"] == "detect_only"
            ),
        },
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    if not args.source.is_file():
        parser.error(f"source does not exist: {args.source}")
    print(json.dumps(audit(args.source), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
