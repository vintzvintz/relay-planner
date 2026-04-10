"""
Recharge une solution JSON depuis plannings/ et régénère les sorties sans relancer le solveur.

Utile pour déboguer les rendus (formatters, Gantt, GPX) sans attendre une résolution complète.
Lit le fichier JSON le plus récent par défaut, ou un fichier spécifié en argument.

Usage:
    python utils/reformat.py                  # dernier planning (html + txt)
    python utils/reformat.py plannings/X/planning.json # fichier spécifique
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from relay import PLANNING_DIR
from relay import Solution


def main():
    parser = argparse.ArgumentParser(description="Régénère les sorties depuis un JSON solution.")
    parser.add_argument("json_file", nargs="?", help=f"Fichier JSON (défaut: le plus récent dans {PLANNING_DIR})")
    args = parser.parse_args()

    if args.json_file:
        json_path = Path(args.json_file)
        sol = Solution.from_json(str(json_path))
    else:
        sol, path = Solution.from_latest()
        json_path = Path(path)

    print(f"Chargement : {json_path}")

    # Crée un répertoire reformat/ au même niveau que le répertoire source
    source_dir = json_path.parent
    reformat_dir = source_dir.parent / f"{source_dir.name}_reformat"
    reformat_dir.mkdir(parents=True, exist_ok=True)

    # re-exporte la solution
    sol.save(base=str(reformat_dir / "planning"))

if __name__ == "__main__":
    main()
