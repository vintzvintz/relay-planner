"""
Copies the most recent planning files from plannings/ to replanif/reference.*
"""

import re
import shutil
from pathlib import Path

PLANNINGS_DIR = Path(__file__).parent.parent / "plannings"
REPLANIF_DIR = Path(__file__).parent.parent / "replanif"

TIMESTAMP_RE = re.compile(r"^planning_(\d{8}_\d{6})\.")


def find_latest_timestamp():
    timestamps = set()
    for f in PLANNINGS_DIR.iterdir():
        m = TIMESTAMP_RE.match(f.name)
        if m:
            timestamps.add(m.group(1))
    if not timestamps:
        raise FileNotFoundError(f"No planning files found in {PLANNINGS_DIR}")
    return max(timestamps)


def main():
    ts = find_latest_timestamp()
    print(f"Latest timestamp: {ts}")

    copied = 0
    for src in PLANNINGS_DIR.glob(f"planning_{ts}.*"):
        ext = src.suffix
        dst = REPLANIF_DIR / f"reference{ext}"
        shutil.copy2(src, dst)
        print(f"  {src.name} -> {dst}")
        copied += 1

    if copied == 0:
        print("No files copied.")
    else:
        print(f"{copied} file(s) copied.")


if __name__ == "__main__":
    main()
