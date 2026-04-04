"""
Génère un profil altimétrique au format gpx/altitude.csv à partir d'une trace GPX.

Usage:
    python utils/gpx_to_altitude_csv.py [--gpx parcours.gpx] [--step 100] [--out gpx/altitude.csv]

Le fichier de sortie utilise le même format que gpx/altitude.csv :
    Distance (m); Altitude (m)
    0;173
    100;172
    ...
"""

import argparse
import math
import xml.etree.ElementTree as ET
from pathlib import Path


GPX_NS = "http://www.topografix.com/GPX/1/1"


def haversine_m(lat1, lon1, lat2, lon2):
    """Distance en mètres entre deux points GPS."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def parse_gpx_track(gpx_path):
    """Retourne une liste de (distance_cumulée_m, altitude_m) pour chaque trackpoint."""
    tree = ET.parse(gpx_path)
    root = tree.getroot()

    points = []
    for trkpt in root.iter(f"{{{GPX_NS}}}trkpt"):
        lat = float(trkpt.attrib["lat"])
        lon = float(trkpt.attrib["lon"])
        ele_el = trkpt.find(f"{{{GPX_NS}}}ele")
        ele = float(ele_el.text) if ele_el is not None else 0.0
        points.append((lat, lon, ele))

    if not points:
        raise ValueError("Aucun trackpoint trouvé dans le fichier GPX.")

    # Calcul des distances cumulées
    result = [(0.0, points[0][2])]
    cum_dist = 0.0
    for i in range(1, len(points)):
        lat1, lon1, _ = points[i - 1]
        lat2, lon2, ele = points[i]
        cum_dist += haversine_m(lat1, lon1, lat2, lon2)
        result.append((cum_dist, ele))

    return result


def resample(track_points, step_m):
    """
    Rééchantillonne le profil à un pas régulier step_m en interpolant linéairement.
    Retourne une liste de (distance_m, altitude_m).
    """
    if not track_points:
        return []

    total_dist = track_points[-1][0]
    output = []
    d = 0.0
    i = 0  # index dans track_points

    while d <= total_dist + 1e-6:
        # Avancer jusqu'au segment qui contient d
        while i + 1 < len(track_points) and track_points[i + 1][0] < d:
            i += 1

        if i + 1 >= len(track_points):
            # Dernier point
            output.append((round(d), track_points[-1][1]))
            break

        d0, alt0 = track_points[i]
        d1, alt1 = track_points[i + 1]

        if d1 == d0:
            alt = alt0
        else:
            t = (d - d0) / (d1 - d0)
            alt = alt0 + t * (alt1 - alt0)

        output.append((round(d), round(alt, 1)))
        d += step_m

    return output


def write_csv(profile, out_path, gpx_name):
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f";;Généré par gpx_to_altitude_csv.py depuis {gpx_name}\n")
        f.write("Distance (m); Altitude (m)\n")
        for dist_m, alt in profile:
            f.write(f"{int(dist_m)};{alt}\n")


def main():
    parser = argparse.ArgumentParser(description="Génère un profil altimétrique CSV depuis une trace GPX.")
    parser.add_argument("--gpx", default="gpx/parcours.gpx", help="Fichier GPX source (défaut: gpx/parcours.gpx)")
    parser.add_argument("--step", type=int, default=100, help="Pas d'échantillonnage en mètres (défaut: 100)")
    parser.add_argument("--out", default="gpx/altitude.csv", help="Fichier CSV de sortie (défaut: gpx/altitude.csv)")
    args = parser.parse_args()

    gpx_path = Path(args.gpx)
    out_path = Path(args.out)

    print(f"Lecture de {gpx_path} ...")
    track = parse_gpx_track(gpx_path)
    total_km = track[-1][0] / 1000
    print(f"  {len(track)} points, distance totale : {total_km:.1f} km")

    print(f"Rééchantillonnage à {args.step} m ...")
    profile = resample(track, args.step)
    print(f"  {len(profile)} points générés")

    print(f"Écriture dans {out_path} ...")
    write_csv(profile, out_path, gpx_path.name)
    print("Terminé.")


if __name__ == "__main__":
    main()
