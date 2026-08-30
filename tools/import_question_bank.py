"""YuReader: atomically publish a validated YuPractice question-bank package.

This is the YuReader-layer publication entry point for real question banks.
YuPractice itself stays a contract/validator tool; this script performs the
publish step on behalf of YuReader:

  1. Re-validates the candidate with ``yupractice.validate`` on a private
     staging copy (the candidate package is never modified).
  2. Refuses publication whenever any blocker exists.
  3. Copies only the canonical YuPractice runtime set into ``question-banks/``
     (manifest.json, questions.jsonl, knowledge-map.json, source-index.json,
     quarantine/, reports/) — workspace scratch files are never copied.
  4. Verifies the manifest-declared SHA-256 for questions, knowledge-map and
     source-index file by file, and confirms quarantine isolation.
  5. Publishes atomically (staging + backup). Replacing an existing same-ID
     bank keeps a recoverable backup and a release record.
  6. Post-publishes a fresh hash/isolation/scratch verification on the runtime
     target. Blocker at any stage leaves the existing runtime bank untouched.

Real questions are only ever stored under the git-ignored ``question-banks/``
runtime root; nothing is committed to Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re as import_re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
DEFAULT_QUESTION_BANK_ROOT = ROOT / "question-banks"
YUPRA_SCRIPTS = TOOLS_ROOT / "yupractice"

# Workspace artifacts that must never enter a runtime question bank.  These
# belong to the build workspace (yubook/yupractice candidate dirs), not the
# published, read-only runtime package.
SCRATCH_NAMES = {
    "outline.json",
    "bank-manifest.json",
    "test-outline.json",
    "build_bank.py",
    "build_bank.exe",
    "__pycache__",
    "_process",
    "dist",
    "notes",
    ".gitkeep",
}

# Canonical runtime file set per the YuPractice package contract.  Everything
# else in the candidate is left behind on purpose.
RUNTIME_FILES = ("manifest.json", "questions.jsonl", "knowledge-map.json", "source-index.json")
RUNTIME_DIRS = ("quarantine", "reports")

BANK_ID_RE = r"[a-z0-9][a-z0-9-]{2,63}"


class ImportError_(RuntimeError):
    """Raised when publication is refused; carries a machine-readable code."""

    def __init__(self, code: str, message: str, details: object = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 顶层必须是 JSON 对象")
    return payload


def import_yupractice() -> None:
    sys.path.insert(0, str(YUPRA_SCRIPTS))
    import yupractice  # noqa: PLC0415

    return None


def validate_package(package_dir: Path) -> dict:
    """Re-run the authoritative YuPractice validator on a package directory."""
    import_yupractice()
    import yupractice  # noqa: PLC0415

    return yupractice.validate_package(package_dir)


def prepare_staging(candidate: Path, root: Path) -> Path:
    """Copy the canonical runtime set from the candidate into a staging dir."""
    manifest_path = candidate / "manifest.json"
    if not manifest_path.is_file():
        raise ImportError_("E001", "candidate 缺少 manifest.json")

    manifest = load_json(manifest_path)
    bank = manifest.get("bank") if isinstance(manifest.get("bank"), dict) else {}
    bank_id = str(bank.get("id") or "")
    if not import_re.fullmatch(BANK_ID_RE, bank_id):
        raise ImportError_("E004", f"bank.id 不是可安全发布的稳定 ID: {bank_id!r}")

    staging = Path(tempfile.mkdtemp(prefix=f".import-{bank_id}-", dir=root))
    try:
        for name in RUNTIME_FILES:
            source = candidate / name
            if not source.is_file():
                raise ImportError_("E005", f"candidate 缺少声明文件 {name}")
            shutil.copy2(source, staging / name)
        for name in RUNTIME_DIRS:
            source = candidate / name
            if source.is_dir():
                shutil.copytree(source, staging / name)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return staging


def declared_hash_verification(package_dir: Path, manifest: dict) -> dict:
    """File-by-file comparison of manifest-declared SHA-256 for the three
    contract files (questions, knowledge-map, source-index)."""
    results: dict[str, bool] = {}
    for key in ("questions", "knowledge_map", "source_index"):
        declaration = manifest.get(key)
        if not isinstance(declaration, dict):
            results[key] = False
            continue
        relative = str(declaration.get("path") or "")
        expected = str(declaration.get("sha256") or "")
        target = package_dir / relative
        if not relative or not expected or not target.is_file() or not target.resolve().is_relative_to(package_dir.resolve()):
            results[key] = False
            continue
        results[key] = sha256_file(target) == expected
    return results


def isolation_verification(package_dir: Path, manifest: dict) -> dict:
    """Confirm the quarantined questions are archive-only and invisible to the
    formal question set (no ID collision and matching counts)."""
    formal_ids: set[str] = set()
    questions_path = package_dir / str((manifest.get("questions") or {}).get("path") or "questions.jsonl")
    if questions_path.is_file():
        for raw in questions_path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
            except ValueError:
                continue
            if isinstance(record, dict) and isinstance(record.get("question_id"), str):
                formal_ids.add(record["question_id"])

    quarantine_dir = package_dir / "quarantine"
    quarantined_ids: set[str] = set()
    q_path = quarantine_dir / "questions.jsonl"
    if q_path.is_file():
        for raw in q_path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
            except ValueError:
                continue
            if isinstance(record, dict) and isinstance(record.get("question_id"), str):
                quarantined_ids.add(record["question_id"])

    declared_q = int(manifest.get("quarantined_count") or 0)
    return {
        "formal_count": len(formal_ids),
        "formal_declared": int(manifest.get("question_count") or 0),
        "quarantined_count": len(quarantined_ids),
        "quarantined_declared": declared_q,
        "isolated": bool(formal_ids.isdisjoint(quarantined_ids)) and len(formal_ids) == int(manifest.get("question_count") or 0) and len(quarantined_ids) == declared_q,
    }


def find_scratch_files(package_dir: Path) -> list[str]:
    """List workspace-scratch paths that would invalidate a published runtime
    question bank (expected to be empty after a clean publish)."""
    found: list[str] = []
    for path in sorted(package_dir.iterdir()):
        name = path.name
        if name in SCRATCH_NAMES:
            found.append(name)
        elif path.is_dir() and name.startswith("."):
            found.append(name)
    for path in sorted(package_dir.rglob("*")):
        if path.name in SCRATCH_NAMES:
            found.append(str(path.relative_to(package_dir).as_posix()))
    return sorted(set(found))


def post_publish_verify(target: Path) -> dict:
    """Verify the published runtime package file-by-file."""
    manifest = load_json(target / "manifest.json")
    hashes = declared_hash_verification(target, manifest)
    isolation = isolation_verification(target, manifest)
    scratch = find_scratch_files(target)
    return {
        "hash_passed": all(hashes.values()),
        "hashes": hashes,
        "isolation": isolation,
        "scratch_files": scratch,
        "scratch_clean": not scratch,
        "verified": all(hashes.values()) and isolation["isolated"] and not scratch,
    }


def write_manifest_flag(package_dir: Path, manifest: dict) -> None:
    """Mark the runtime manifest as imported (derived metadata only, never
    covered by the three declared hashes, so re-import remains safe)."""
    manifest["imported"] = True
    manifest["imported_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    target = package_dir / "manifest.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def release_record_path(root: Path, bank_id: str) -> Path:
    return root / ".import-releases" / f"{bank_id}.json"


def publish_staging(staging: Path, root: Path, bank_id: str, manifest: dict) -> dict:
    """Atomically move the validated staging into the runtime root.

    On replacement, the previous bank is kept as a recoverable backup under
    ``.backup-<bank_id>-<timestamp>`` and a release record is appended to
    ``.import-releases/<bank_id>.json``.  A failed replacement restores the
    previous runtime bank untouched.
    """
    target = (root / bank_id).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ImportError_("E004", "bank target escapes question-bank root") from exc

    replaced = False
    backup: str | None = None
    release: dict | None = None
    if target.exists():
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup_dir = root / f".backup-{bank_id}-{timestamp}"
        target.replace(backup_dir)
        backup = backup_dir.name
        replaced = True
        try:
            staging.replace(target)
        except Exception:
            if backup_dir.exists() and not target.exists():
                backup_dir.replace(target)
            shutil.rmtree(staging, ignore_errors=True)
            raise
        release = {
            "bank_id": bank_id,
            "replaced_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "previous_manifest_sha256": sha256_file(backup_dir / "manifest.json") if (backup_dir / "manifest.json").is_file() else "",
            "previous_question_count": _manifest_question_count(backup_dir),
            "backup": backup,
            "new_question_count": _manifest_question_count(target),
        }
        release_path = release_record_path(root, bank_id)
        history: list[dict] = []
        if release_path.is_file():
            try:
                history = json.loads(release_path.read_text(encoding="utf-8-sig"))
                if not isinstance(history, list):
                    history = []
            except (OSError, json.JSONDecodeError):
                history = []
        history.append(release)
        release_path.parent.mkdir(parents=True, exist_ok=True)
        release_path.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        staging.replace(target)
    return {"replaced": replaced, "backup": backup, "release": release}


def _manifest_question_count(package_dir: Path) -> int:
    try:
        manifest = load_json(package_dir / "manifest.json")
        return int(manifest.get("question_count") or 0)
    except (OSError, ValueError, json.JSONDecodeError):
        return 0


def command_import(candidate: Path, root: Path) -> dict:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)

    staging = prepare_staging(candidate, root)
    try:
        report = validate_package(staging)
        if report.get("quality", {}).get("blocker_count", 0) > 0:
            raise ImportError_(
                "blocked",
                f"candidate 存在 {report['quality']['blocker_count']} 个 blocker，拒绝发布",
                report.get("blockers"),
            )
        manifest = load_json(staging / "manifest.json")
        bank_id = str(manifest["bank"]["id"])

        hashes = declared_hash_verification(staging, manifest)
        if not all(hashes.values()):
            raise ImportError_("hash_mismatch", "candidate 的 manifest 声明哈希与文件不一致", hashes)
        isolation = isolation_verification(staging, manifest)
        if not isolation["isolated"]:
            raise ImportError_("quarantine_leak", "隔离题泄漏或题量不一致", isolation)
        scratch = find_scratch_files(staging)
        if scratch:
            raise ImportError_("scratch_files", "staging 包含不应发布的 workspace 文件", scratch)

        write_manifest_flag(staging, manifest)
        publish = publish_staging(staging, root, bank_id, manifest)
        target = root / bank_id
        verified = post_publish_verify(target)
        return {
            "status": "published",
            "bank_id": bank_id,
            "target": str(target),
            "quality": report.get("quality"),
            "summary": report.get("summary"),
            "warning_count": len(report.get("warnings") or []),
            "verified": verified,
            "publish": publish,
        }
    except ImportError_ as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise ImportError_("runtime", str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="import-question-bank", description="YuReader 题库原子发布入口（仅发布，不做作答/UI）")
    parser.add_argument("package", type=Path, help="YuPractice 候选包目录（validate 通过后才能发布）")
    parser.add_argument("--question-bank-root", type=Path, default=DEFAULT_QUESTION_BANK_ROOT, help="正式题库运行时根目录（默认项目根 question-banks/）")
    parser.add_argument("--json", action="store_true", help="仅输出机器可读 JSON")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    originals = sys.stdout, sys.stderr
    for stream in originals:
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        result = command_import(args.package, args.question_bank_root)
    except ImportError_ as exc:
        payload = {"status": "error", "code": exc.code, "message": str(exc), "details": exc.details}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    except Exception as exc:
        print(json.dumps({"status": "error", "code": "runtime", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())