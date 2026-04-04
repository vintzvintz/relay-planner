"""
Echantillonne un parcours GPX tous les STEP_M mètres.
Produit un fichier JSON : liste de (numero_segment, distance_m, latitude, longitude).
"""

import json
import math
import xml.etree.ElementTree as ET

GPX_FILE = "gpx/parcours.gpx"
OUTPUT_FILE = "gpx/access_points.json"
STEP_M = 2500

GPX_NS = "http://www.topografix.com/GPX/1/1"


def haversine(lat1, lon1, lat2, lon2):
    """Distance en mètres entre deux points GPS."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def load_track_points(gpx_path):
    tree = ET.parse(gpx_path)
    root = tree.getroot()
    points = []
    for trkpt in root.iter(f"{{{GPX_NS}}}trkpt"):
        lat = float(trkpt.attrib["lat"])
        lon = float(trkpt.attrib["lon"])
        points.append((lat, lon))
    return points


def sample_track(points, step_m):
    if not points:
        return []

    samples = []
    seg_num = 0
    cumulative_dist = 0.0
    next_threshold = 0.0

    # Premier point
    samples.append({
        "segment": seg_num,
        "distance_m": 0,
        "lat": points[0][0],
        "lon": points[0][1],
    })
    next_threshold = step_m

    prev_lat, prev_lon = points[0]
    prev_dist = 0.0

    for lat, lon in points[1:]:
        d = haversine(prev_lat, prev_lon, lat, lon)
        new_dist = cumulative_dist + d

        # Interpoler tous les seuils franchis entre prev_dist et new_dist
        while next_threshold <= new_dist:
            seg_num += 1
            # Fraction du segment courant où se trouve le seuil
            frac = (next_threshold - cumulative_dist) / d if d > 0 else 0.0
            ilat = prev_lat + frac * (lat - prev_lat)
            ilon = prev_lon + frac * (lon - prev_lon)
            samples.append({
                "segment": seg_num,
                "distance_m": round(next_threshold),
                "lat": round(ilat, 6),
                "lon": round(ilon, 6),
            })
            next_threshold += step_m

        cumulative_dist = new_dist
        prev_lat, prev_lon = lat, lon

    # Dernier point : fin réelle du parcours
    last_lat, last_lon = points[-1]
    samples.append({
        "segment": seg_num + 1,
        "distance_m": round(cumulative_dist),
        "lat": round(last_lat, 6),
        "lon": round(last_lon, 6),
    })

    return samples


def main():
    print(f"Lecture de {GPX_FILE} ...")
    points = load_track_points(GPX_FILE)
    print(f"  {len(points)} points GPX chargés")

    samples = sample_track(points, STEP_M)
    total_km = (samples[-1]["distance_m"] / 1000) if samples else 0
    print(f"  {len(samples)} points d'accès (pas={STEP_M} m, total ≈ {total_km:.1f} km)")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(samples, f, indent=2, ensure_ascii=False)
    print(f"Résultat écrit dans {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
