"""
Recharge la solution JSON la plus récente depuis plannings/ et régénère le HTML.
Usage: python reformat.py [fichier.json]
"""

import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import data
import solution


def load_relais_list_from_json(path, constraints):
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)

    relais_list = []
    for row in rows:
        relais_list.append({
            "runner": row["coureur"],
            "k": None,  # non utilisé par solution.py
            "start": row["debut_seg"],
            "end": row["fin_seg"],
            "size": row["fin_seg"] - row["debut_seg"],
            "km": row["distance_km"],
            "flex": row["flex"],
            "solo": row["solo"],
            "night": row["nuit"],
            "partner": row["partenaire"],
            "rest_h": row["rest_h"],
        })

    return relais_list


def main():
    if len(sys.argv) > 1:
        json_path = sys.argv[1]
    else:
        files = sorted(glob.glob("plannings/*.json"))
        if not files:
            print("Aucun fichier JSON trouvé dans plannings/", file=sys.stderr)
            sys.exit(1)
        json_path = files[-1]

    print(f"Chargement : {json_path}")

    constraints = data.build_constraints()
    relais_list = load_relais_list_from_json(json_path, constraints)
    sol = solution.RelaySolution(relais_list, constraints)

    if not sol.valid:
        print("Attention : la solution ne passe pas les vérifications.", file=sys.stderr)

    html_path = "plannings/test.html"
    sol.to_html(html_path)
    print(f"HTML généré : {html_path}")


if __name__ == "__main__":
    main()
