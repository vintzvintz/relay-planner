"""
Recharge la solution JSON la plus récente depuis plannings/ et régénère le HTML.
Usage: python utils/reformat.py [fichier.json]
"""

import glob
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from relay import Solution


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

    sol = Solution.from_json(json_path)

    if not sol.valid:
        print("Attention : la solution ne passe pas les vérifications.", file=sys.stderr)

    html_path = "plannings/tmp.html"
    sol.to_html(html_path)
    print(f"HTML généré : {html_path}")

    if sol.constraints.parcours_gpx:
        from relay.gpx import solution_to_gpx, solution_to_kml
        gpx_path = "plannings/tmp.gpx"
        solution_to_gpx(sol, sol.constraints.parcours_gpx, gpx_path)
        print(f"GPX généré  : {gpx_path}")
        # kml_path = "plannings/tmp.kml"
        # solution_to_kml(sol, sol.constraints.parcours_gpx, kml_path)
        # print(f"KML généré  : {kml_path}")


if __name__ == "__main__":
    main()
