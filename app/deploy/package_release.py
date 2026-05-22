from __future__ import annotations

import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT.parent / "welopc-ai-signal-radar.zip"

EXCLUDED_DIRS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "auth",
}

EXCLUDED_TOP_LEVEL = {
    "data",
    "logs",
    "reports",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".log",
    ".zip",
}


def should_skip(path: Path) -> bool:
    rel_parts = path.relative_to(ROOT).parts
    if not rel_parts:
        return False
    if rel_parts[0] in EXCLUDED_TOP_LEVEL:
        return True
    if any(part in EXCLUDED_DIRS for part in rel_parts):
        return True
    if path.suffix in EXCLUDED_SUFFIXES:
        return True
    return False


def main() -> None:
    if OUT.exists():
        OUT.unlink()

    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ROOT.rglob("*")):
            if should_skip(path):
                continue
            if path.is_dir():
                continue
            arcname = Path(ROOT.name) / path.relative_to(ROOT)
            archive.write(path, arcname.as_posix())

    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"created {OUT} ({size_mb:.2f} MB)")

    # Keep a copy inside the repo for deployers who receive only the folder.
    local_copy = ROOT / OUT.name
    if local_copy.exists():
        local_copy.unlink()
    shutil.copy2(OUT, local_copy)
    print(f"copied {local_copy}")


if __name__ == "__main__":
    main()
