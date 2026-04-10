"""
Copie les fichiers du planning le plus récent de plannings/ vers replanif/reference.*.

Détecte automatiquement le sous-répertoire le plus récent dans plannings/ (format
<YYYYMMDD_HHMMSS>_<action>/) et copie tous les formats associés (.txt, .csv, .json,
.html, .gpx, .kml) vers replanif/reference.* en écrasant l'ancien.

À lancer avant une replanification pour s'assurer que replanif/reference.json correspond
bien au dernier planning produit.

Usage:
    python utils/update_reference.py
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from relay import PLANNING_DIR

PLANNINGS_DIR = Path(PLANNING_DIR)
REPLANIF_DIR = PLANNINGS_DIR.parent / "replanif"


def find_latest_run_dir():
    run_dirs = sorted(
        (d for d in PLANNINGS_DIR.iterdir() if d.is_dir()),
        key=lambda d: d.name,
        reverse=True,
    )
    if not run_dirs:
        raise FileNotFoundError(f"No run directories found in {PLANNINGS_DIR}")
    return run_dirs[0]


def main():
    run_dir = find_latest_run_dir()
    print(f"Latest run: {run_dir.name}")

    REPLANIF_DIR.mkdir(parents=True, exist_ok=True)

    copied = 0
    for src in run_dir.iterdir():
        if not src.is_file():
            continue
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
