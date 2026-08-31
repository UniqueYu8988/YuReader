from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "assemble_mineru_chunks.py"
SPEC = importlib.util.spec_from_file_location("assemble_mineru_chunks", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(module)


class AssembleMineruChunksTests(unittest.TestCase):
    def test_ranges_must_cover_every_page_once(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            chunks = []
            for start, end in ((0, 1), (2, 3)):
                folder = base / f"pages-{start:03d}-{end:03d}" / "book" / "ocr"
                folder.mkdir(parents=True)
                markdown = folder / "book.md"
                markdown.write_text(f"pages {start}-{end}", encoding="utf-8")
                chunks.append((start, end, markdown, None))
            module.validate_ranges(chunks, 4)
            with self.assertRaisesRegex(ValueError, "expected 4"):
                module.validate_ranges(chunks[:-1], 4)

    def test_asset_collision_must_have_identical_content(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            first = base / "first"
            second = base / "second"
            output = base / "output"
            first.mkdir()
            second.mkdir()
            (first / "same.jpg").write_bytes(b"first")
            (second / "same.jpg").write_bytes(b"second")
            chunks = [(0, 0, base / "a.md", first), (1, 1, base / "b.md", second)]
            with self.assertRaisesRegex(ValueError, "collision"):
                module.copy_assets(chunks, output)


if __name__ == "__main__":
    unittest.main()
