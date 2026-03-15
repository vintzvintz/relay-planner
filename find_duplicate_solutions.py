"""
Cherche les solutions JSON identiques dans enumerate_solutions/.
Deux solutions sont identiques si elles couvrent exactement les mêmes relais :
- même segment (debut_seg, fin_seg)
- même coureur(s) (paire triée pour les binômes)
L'ordre des entrées JSON n'est pas pris en compte.
"""

import hashlib
import json
from collections import defaultdict
from pathlib import Path

SOLUTIONS_DIR = Path("enumerate_solutions")


def canonical_key(json_path: Path) -> str:
    """Retourne une clé canonique représentant la solution (insensible à l'ordre des entrées)."""
    relays = set()
    seen_pairs = set()  # pour dédupliquer les binômes (2 entrées → 1 clé)

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    for row in data:
        debut_seg = row["debut_seg"]
        fin_seg = row["fin_seg"]
        coureur = row["coureur"]
        partenaire = row["partenaire"]
        nuit = row["nuit"]

        if partenaire:
            # binôme : normalise la paire
            pair = tuple(sorted([coureur, partenaire]))
            key = (debut_seg, fin_seg, pair, nuit)
            if key not in seen_pairs:
                seen_pairs.add(key)
                relays.add((debut_seg, fin_seg, "binome", pair[0], pair[1], nuit))
        else:
            relays.add((debut_seg, fin_seg, "solo", coureur, "", nuit))

    # trie pour obtenir une représentation stable
    sorted_relays = sorted(relays)
    digest = hashlib.sha256(json.dumps(sorted_relays).encode()).hexdigest()
    return digest


def main():
    json_files = sorted(SOLUTIONS_DIR.glob("*.json"))
    if not json_files:
        print(f"Aucun fichier JSON trouvé dans {SOLUTIONS_DIR}/")
        return

    print(f"{len(json_files)} fichiers JSON trouvés.\n")

    key_to_files: dict[str, list[Path]] = defaultdict(list)
    for path in json_files:
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
