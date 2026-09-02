"""Compatibility entry point for the canonical Markdown importer.

New automation should call ``tools/import_markdown.py`` directly. This shim is
kept so older local commands continue to work without maintaining two copies of
the importer.
"""

from tools.import_markdown import *  # noqa: F403 - intentional legacy re-export


if __name__ == "__main__":
    main()
