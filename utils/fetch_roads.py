"""
Interroge l'API Overpass pour récupérer les routes carrossables dans un
corridor de RADIUS_M mètres autour des points d'accès du parcours.

Le parcours est découpé en NB_CHUNKS tranches pour rester sous les limites
de l'API. Chaque chunk réussi est sauvegardé dans gpx/chunk_<n>_of_<N>.json.
Les chunks manquants sont seuls re-téléchargés. Quand tous les chunks sont
disponibles, ils sont fusionnés dans OUTPUT_FILE.
"""

import json
import os
import time
import urllib.request
import urllib.parse

ACCESS_POINTS_FILE = "gpx/segment_coords.json"
OUTPUT_FILE = "gpx/roads.json"
CHUNKS_DIR = "gpx"

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

RADIUS_M = 2000
NB_CHUNKS = 5

HIGHWAY_FILTER = (
    "motorway|motorway_link|trunk|trunk_link|primary|primary_link"
    "|secondary|secondary_link|tertiary|tertiary_link"
    "|unclassified|residential|service|road"
)

RETRY_DELAY_S = 60
REQUEST_PAUSE_S = 10  # pause entre requêtes pour respecter l'API

# Paramètres de test : limiter à un sous-ensemble de segments (None = tout le parcours)
SEG_START = None   # index du premier segment à inclure  (None = tout le parcours)
SEG_COUNT = None   # nombre de segments à inclure        (None = jusqu'à la fin)


def chunk_path(i, total):
    return os.path.join(CHUNKS_DIR, f"chunk_{i+1}_of_{total}.json")


def build_query(points, radius, highway_filter):
    """Construit une requête Overpass QL avec `around:` sur une liste de points."""
    coord_str = ",".join(f"{p['lat']},{p['lon']}" for p in points)
    around = f"around:{radius},{coord_str}"
    q = f"""
[out:json][timeout:180];
(
  way["highway"~"^({highway_filter})$"]({around});
);
out geom;
"""
    return q.strip()


def fetch_overpass(query, attempt=1, max_attempts=3):
    data = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(OVERPASS_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=200) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        if attempt < max_attempts:
            print(f"  Erreur ({e}), nouvelle tentative dans {RETRY_DELAY_S}s...")
            time.sleep(RETRY_DELAY_S)
            return fetch_overpass(query, attempt + 1, max_attempts)
        raise


def merge_chunks(chunk_files):
    """Fusionne les chunks en dédupliquant par id."""
    seen = set()
    elements = []
    for path in chunk_files:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for el in data.get("elements", []):
            key = (el["type"], el["id"])
            if key not in seen:
                seen.add(key)
                elements.append(el)
    return elements


def main():
    with open(ACCESS_POINTS_FILE, encoding="utf-8") as f:
        points = json.load(f)

    print(f"{len(points)} points chargés depuis {ACCESS_POINTS_FILE}")

    if SEG_START is not None:
        end = SEG_START + (SEG_COUNT or len(points))
        points = [p for p in points if SEG_START <= p["segment"] < end]
        print(f"Mode test : segments {points[0]['segment']}–{points[-1]['segment']} "
              f"({len(points)} points)")

    chunk_size = (len(points) + NB_CHUNKS - 1) // NB_CHUNKS
    chunks_pts = []
    for i in range(NB_CHUNKS):
        start = i * chunk_size
        end = min(start + chunk_size + 1, len(points))  # +1 recouvrement
        chunks_pts.append(points[start:end])

    # Télécharger uniquement les chunks manquants
    for i, pts in enumerate(chunks_pts):
        path = chunk_path(i, NB_CHUNKS)
        if os.path.exists(path):
            print(f"Chunk {i+1}/{NB_CHUNKS} : déjà disponible ({path}), ignoré.")
            continue

        print(f"Chunk {i+1}/{NB_CHUNKS} : segments {pts[0]['segment']}–{pts[-1]['segment']} "
              f"({len(pts)} pts)...")
        try:
            result = fetch_overpass(build_query(pts, RADIUS_M, HIGHWAY_FILTER))
        except Exception as e:
            print(f"  ÉCHEC définitif : {e}")
            print("  Relancez le script pour réessayer les chunks manquants.")
            return

        nb = len(result.get("elements", []))
        print(f"  → {nb} éléments reçus, sauvegarde dans {path}")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)

        if i < NB_CHUNKS - 1:
            time.sleep(REQUEST_PAUSE_S)

    # Vérifier que tous les chunks sont présents
    missing = [chunk_path(i, NB_CHUNKS) for i in range(NB_CHUNKS)
               if not os.path.exists(chunk_path(i, NB_CHUNKS))]
    if missing:
        print(f"\nChunks manquants : {missing}")
        print("Relancez le script pour télécharger les chunks manquants.")
        return

    # Fusionner
    all_paths = [chunk_path(i, NB_CHUNKS) for i in range(NB_CHUNKS)]
    print(f"\nTous les chunks disponibles, fusion dans {OUTPUT_FILE}...")
    elements = merge_chunks(all_paths)
    nb_ways = sum(1 for e in elements if e["type"] == "way")
    print(f"Fusion : {nb_ways} ways")

    output = {
        "source": "Overpass API",
        "radius_m": RADIUS_M,
        "nb_chunks": NB_CHUNKS,
        "nb_access_points": len(points),
        "elements": elements,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False)
    print(f"Résultat écrit dans {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
