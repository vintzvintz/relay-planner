"""
Vérifie que les configurations de binômes générées en phase 2 par enumerate.py
sont toutes distinctes.

Une configuration est définie par l'ensemble des paires (coureur, partenaire, debut_seg, fin_seg)
pour tous les relais non-solo, normalisé pour que chaque paire apparaisse une seule fois
(coureur < partenaire alphabétiquement).

Usage:
    python check_configs_unique.py [run_ts]

    run_ts (optionnel) : filtre sur un run spécifique, ex: "20260315_204953"
    Sans argument : analyse tous les runs présents dans enumerate_solutions/
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

OUTDIR = Path("enumerate_solutions")


def load_config_fingerprint(json_path: Path) -> frozenset:
    """Extrait l'empreinte de configuration (ensemble des binômes) depuis un JSON place_00."""
    with open(json_path, encoding="utf-8") as f:
        relais = json.load(f)

    binomes = set()
    for relay in relais:
        if relay["solo"]:
            continue
        r1, r2 = relay["coureur"], relay["partenaire"]
        # Normalise l'ordre pour éviter les doublons (A,B) vs (B,A)
        pair = (min(r1, r2), max(r1, r2), relay["debut_seg"], relay["fin_seg"])
        binomes.add(pair)

    return frozenset(binomes)


def check_configs(run_filter: str | None = None):
    if not OUTDIR.exists():
        print(f"Répertoire '{OUTDIR}' introuvable.")
        sys.exit(1)

    # Récupère tous les fichiers place_00 (= configs de phase 2)
    pattern = f"run_*_config_*_place_00.json"
    files = sorted(OUTDIR.glob(pattern))

    if run_filter:
        files = [f for f in files if run_filter in f.name]

    if not files:
        print("Aucun fichier de configuration trouvé.")
        sys.exit(1)

    # Groupe par run
    runs: dict[str, list[Path]] = defaultdict(list)
    for f in files:
        # ex: run_20260315_204953_config_001_place_00.json
        parts = f.stem.split("_")
        run_ts = f"{'_'.join(parts[1:3])}"  # "20260315_204953"
        runs[run_ts].append(f)

    total_ok = True

    for run_ts, run_files in sorted(runs.items()):
        print(f"\n=== Run {run_ts} — {len(run_files)} configuration(s) ===")

        fingerprints: dict[frozenset, Path] = {}
        duplicates = []

        for json_path in sorted(run_files):
            fp = load_config_fingerprint(json_path)
            if fp in fingerprints:
                duplicates.append((json_path, fingerprints[fp]))
            else:
                fingerprints[fp] = json_path

        if duplicates:
            total_ok = False
            print(f"  DOUBLONS DÉTECTÉS ({len(duplicates)}) :")
            for dup, original in duplicates:
                print(f"    {dup.name}  ==  {original.name}")
        else:
            print(f"  OK — toutes les configurations sont distinctes.")

        # Détail des configs
        for json_path in sorted(run_files):
            fp = load_config_fingerprint(json_path)
            n_binomes = len(fp)
            runners_in_binomes = {r for pair in fp for r in pair[:2]}
            print(f"    {json_path.name} : {n_binomes} binôme(s), "
                  f"{len(runners_in_binomes)} coureur(s) impliqué(s)")

    print()
    if total_ok:
        print("Résultat global : toutes les configurations sont uniques.")
        sys.exit(0)
    else:
        print("Résultat global : des doublons ont été trouvés !")
        sys.exit(1)


if __name__ == "__main__":
    run_filter = sys.argv[1] if len(sys.argv) > 1 else None
    check_configs(run_filter)
