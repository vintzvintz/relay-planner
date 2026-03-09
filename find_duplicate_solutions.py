"""
Cherche les solutions CSV identiques dans enumerate_solutions/.
Deux solutions sont identiques si elles couvrent exactement les mêmes relais :
- même segment (km_debut, km_fin)
- même coureur(s) (paire triée pour les binômes)
L'ordre des lignes CSV n'est pas pris en compte.
"""

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

SOLUTIONS_DIR = Path("enumerate_solutions")


def canonical_key(csv_path: Path) -> str:
    """Retourne une clé canonique représentant la solution (insensible à l'ordre des lignes)."""
    relays = set()
    seen_pairs = set()  # pour dédupliquer les binômes (2 lignes → 1 entrée)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            km_debut = row["km_debut"]
            km_fin = row["km_fin"]
            coureur = row["coureur"].strip()
            partenaire = row["partenaire"].strip()
            nuit = row["nuit"].strip()
            solo = row["solo"].strip()

            if partenaire:
                # binôme : normalise la paire
                pair = tuple(sorted([coureur, partenaire]))
                key = (km_debut, km_fin, pair, nuit)
                if key not in seen_pairs:
                    seen_pairs.add(key)
                    relays.add((km_debut, km_fin, "binome", pair[0], pair[1], nuit))
            else:
                relays.add((km_debut, km_fin, "solo", coureur, "", nuit))

    # trie pour obtenir une représentation stable
    sorted_relays = sorted(relays)
    digest = hashlib.sha256(json.dumps(sorted_relays).encode()).hexdigest()
    return digest


def main():
    csv_files = sorted(SOLUTIONS_DIR.glob("*.csv"))
    if not csv_files:
        print(f"Aucun fichier CSV trouvé dans {SOLUTIONS_DIR}/")
        return

    print(f"{len(csv_files)} fichiers CSV trouvés.\n")

    key_to_files: dict[str, list[Path]] = defaultdict(list)
    for path in csv_files:
        try:
            key = canonical_key(path)
            key_to_files[key].append(path)
        except Exception as e:
            print(f"Erreur sur {path.name}: {e}")

    duplicates = {k: v for k, v in key_to_files.items() if len(v) > 1}
    unique_count = sum(1 for v in key_to_files.values() if len(v) == 1)

    print(f"Solutions distinctes : {len(key_to_files)}")
    print(f"  dont uniques       : {unique_count}")
    print(f"  dont dupliquées    : {len(duplicates)} groupes\n")

    if duplicates:
        print("=== Groupes de doublons ===")
        for i, (key, files) in enumerate(sorted(duplicates.items()), 1):
            print(f"\nGroupe {i} ({len(files)} fichiers identiques) :")
            for f in files:
                print(f"  {f.name}")
    else:
        print("Aucun doublon trouvé.")


if __name__ == "__main__":
    main()
