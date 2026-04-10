"""
Extrait les points-relais d'un export KML Google Earth et génère gpx/relay_points.json.

Lit le dossier "Points-relais" (et ses sous-dossiers) du KML, projette chaque point sur la
trace "Lyon---Fessenheim" pour calculer son point kilométrique, puis trie les points par km
croissant. Vérifie la présence d'un point de départ (km 0) et d'un point d'arrivée.

Le fichier de sortie (défaut : gpx/relay_points.json) est au format [{km, lat, lon, alt}, ...]
et constitue le fichier de waypoints utilisé par Constraints(waypoints=...).

Usage:
    python utils/kml_to_relay_points.py [chemin_kml] [--out output.json]

    chemin_kml : fichier KML source (défaut : gpx/pts relais lys-fsh.kml)
    --out      : fichier JSON de sortie (défaut : gpx/relay_points.json)
"""

import argparse
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

KML_NS = "http://www.opengis.net/kml/2.2"
ROOT_FOLDER = "Points-relais"
TOLERANCE_KM = 1.0   # détection points de départ/arrivée

def parse_coordinates(coord_text: str) -> list[tuple[float, float, float | None]]:
    """Parse une chaîne 'lon,lat[,alt] lon,lat[,alt] ...' en liste de tuples."""
    points = []
    for token in coord_text.strip().split():
        parts = token.split(",")
        if len(parts) >= 2:
            lon = float(parts[0])
            lat = float(parts[1])
            alt = float(parts[2]) if len(parts) >= 3 else None
            points.append((lon, lat, alt))
    return points


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance en mètres entre deux points GPS (formule haversine)."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def build_cumulative_km(track: list[tuple[float, float, float | None]]) -> list[float]:
    """Construit le tableau des distances cumulées (en km) le long du tracé."""
    cum = [0.0]
    for i in range(1, len(track)):
        lon1, lat1, _ = track[i - 1]
        lon2, lat2, _ = track[i]
        cum.append(cum[-1] + haversine_m(lat1, lon1, lat2, lon2) / 1000)
    return cum


def nearest_km_on_track(
    lat: float,
    lon: float,
    track: list[tuple[float, float, float | None]],
    cum_km: list[float],
) -> float:
    """
    Projette (lat, lon) sur le tracé et retourne le point kilométrique.
    Cherche le segment le plus proche, puis interpole linéairement.
    """
    best_km = 0.0
    best_dist = float("inf")

    for i in range(len(track) - 1):
        lon1, lat1, _ = track[i]
        lon2, lat2, _ = track[i + 1]

        # Projection du point sur le segment [P1, P2]
        dx = lon2 - lon1
        dy = lat2 - lat1
        seg_len_sq = dx * dx + dy * dy
        if seg_len_sq == 0:
            t = 0.0
        else:
            t = ((lon - lon1) * dx + (lat - lat1) * dy) / seg_len_sq
            t = max(0.0, min(1.0, t))

        proj_lon = lon1 + t * dx
        proj_lat = lat1 + t * dy
        dist = haversine_m(lat, lon, proj_lat, proj_lon)

        if dist < best_dist:
            best_dist = dist
            seg_km = cum_km[i + 1] - cum_km[i]
            best_km = cum_km[i] + t * seg_km

    return best_km


def find_folder(root: ET.Element, name_fragment: str) -> ET.Element | None:
    """Trouve récursivement un Folder dont le <name> contient name_fragment."""
    for elem in root.iter(f"{{{KML_NS}}}Folder"):
        name_el = elem.find(f"{{{KML_NS}}}name")
        if name_el is not None and name_fragment.lower() in (name_el.text or "").lower():
            return elem
    return None


def extract_track(root: ET.Element) -> list[tuple[float, float, float | None]]:
    """Extrait le tracé LineString du dossier Lyon---Fessenheim."""
    parcours_folder = find_folder(root, "Lyon---Fessenheim")
    if parcours_folder is None:
        sys.exit("Dossier 'Lyon---Fessenheim' introuvable dans le KML.")

    for ls in parcours_folder.iter(f"{{{KML_NS}}}LineString"):
        coords_el = ls.find(f"{{{KML_NS}}}coordinates")
        if coords_el is not None and coords_el.text:
            track = parse_coordinates(coords_el.text)
            print(f"Tracé chargé : {len(track)} points, {build_cumulative_km(track)[-1]:.1f} km")
            return track

    sys.exit("Aucune LineString trouvée dans le dossier parcours.")


def extract_relay_points(root: ET.Element) -> list[dict]:
    """Extrait tous les Placemark (Point) du dossier ROOT_FOLDER et tous ses sous-dossiers."""
    relay_folder = find_folder(root, ROOT_FOLDER)
    if relay_folder is None:
        sys.exit(f"Dossier '{ROOT_FOLDER}' introuvable dans le KML.")

    placemarks = []
    for folder in relay_folder.iter(f"{{{KML_NS}}}Folder"):
        folder_name_el = folder.find(f"{{{KML_NS}}}name")
        folder_name = (folder_name_el.text or "").strip() if folder_name_el is not None else ""

        for pm in folder.findall(f"{{{KML_NS}}}Placemark"):
            point_el = pm.find(f"{{{KML_NS}}}Point")
            if point_el is None:
                continue  # ignorer lignes/polygones

            coords_el = point_el.find(f"{{{KML_NS}}}coordinates")
            if coords_el is None or not coords_el.text:
                continue

            pts = parse_coordinates(coords_el.text)
            if not pts:
                continue
            lon, lat, alt = pts[0]

            # description optionnelle (CDATA)
            desc_el = pm.find(f"{{{KML_NS}}}description")
            desc = ""
            if desc_el is not None and desc_el.text:
                # nettoyer les balises HTML basiques
                import re
                desc = re.sub(r"<[^>]+>", "", desc_el.text).strip()

            name_el = pm.find(f"{{{KML_NS}}}name")
            name = (name_el.text or "").strip() if name_el is not None else ""

            placemarks.append({
                "lat": lat,
                "lon": lon,
                "alt": alt,
                "name": name,
                "description": desc,
                "folder": folder_name,
            })

    print(f"Points-relais extraits : {len(placemarks)}")
    return placemarks


def main():
    parser = argparse.ArgumentParser(description="Extrait les points-relais du KML")
    parser.add_argument(
        "kml",
        nargs="?",
        default="gpx/pts relais lys-fsh.kml",
        help="Chemin vers le fichier KML (défaut: gpx/pts relais lys-fsh.kml)",
    )
    parser.add_argument(
        "--out",
        default="gpx/relay_points.json",
        help="Fichier JSON de sortie (défaut: gpx/relay_points.json)",
    )
    args = parser.parse_args()

    kml_path = Path(args.kml)
    if not kml_path.exists():
        sys.exit(f"Fichier introuvable : {kml_path}")

    tree = ET.parse(kml_path)
    root = tree.getroot()

    track = extract_track(root)
    cum_km = build_cumulative_km(track)
    relay_points_raw = extract_relay_points(root)

    # Calcul du point kilométrique + construction du JSON final
    result = []
    for p in relay_points_raw:
        km = nearest_km_on_track(p["lat"], p["lon"], track, cum_km)
        entry: dict = {
            "km": round(km, 2),
            "lat": p["lat"],
            "lon": p["lon"],
        }
        if p["alt"] is not None:
            entry["alt"] = round(p["alt"], 1)
        if p["description"]:
            entry["description"] = p["description"]
        result.append(entry)

    # Tri par km croissant
    result.sort(key=lambda x: x["km"])

    # Vérification départ et arrivée
    total_km = cum_km[-1]

    if not result or result[0]["km"] > TOLERANCE_KM:
        nearest = f"km {result[0]['km']:.2f}" if result else "aucun point"
        sys.exit(
            f"Aucun point de départ (km 0) trouvé dans '{ROOT_FOLDER}'. "
            f"Point le plus proche du départ : {nearest}."
        )
    if not result or abs(result[-1]["km"] - total_km) > TOLERANCE_KM:
        sys.exit(
            f"Aucun point d'arrivée (km {total_km:.1f}) trouvé dans '{ROOT_FOLDER}'. "
            f"Point le plus proche de l'arrivée : km {result[-1]['km']:.2f}."
        )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Sortie écrite dans {out_path} ({len(result)} points)")


if __name__ == "__main__":
    main()
