#!/usr/bin/env python3
"""
Convertit une trace GPX en KML ou KMZ pour import dans Google Earth ou Google Mes Cartes.

Génère un fichier KML contenant la trace complète et des marqueurs tous les N km (défaut 10 km).
Le KMZ est une version compressée (zip) du KML, compatible avec tous les outils Google.

Usage:
    python utils/gpx_to_kml.py [fichier.gpx] [-o sortie.kml] [--kmz] [--step 10]

    fichier.gpx  : trace source (défaut : gpx/parcours.gpx)
    -o           : fichier de sortie (défaut : même nom que l'entrée, extension .kml ou .kmz)
    --kmz        : forcer la sortie en KMZ (archive zip)
    --step KM    : intervalle entre les marqueurs kilométriques (défaut : 10)
"""

import argparse
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


GPX_NS = "http://www.topografix.com/GPX/1/1"


def parse_gpx(path: Path) -> tuple[str, list[tuple[float, float, float | None]]]:
    """Return (track_name, [(lon, lat, ele), ...])."""
    tree = ET.parse(path)
    root = tree.getroot()

    name_el = root.find(f".//{{{GPX_NS}}}name")
    track_name = name_el.text.strip() if name_el is not None else path.stem

    points = []
    for trkpt in root.iter(f"{{{GPX_NS}}}trkpt"):
        lat = float(trkpt.attrib["lat"])
        lon = float(trkpt.attrib["lon"])
        ele_el = trkpt.find(f"{{{GPX_NS}}}ele")
        ele = float(ele_el.text) if ele_el is not None else None
        points.append((lon, lat, ele))

    return track_name, points


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Distance in metres between two WGS84 points."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def interpolate(p1: tuple, p2: tuple, t: float) -> tuple[float, float, float]:
    """Linear interpolation between two (lon, lat, ele) points, t in [0,1]."""
    lon = p1[0] + t * (p2[0] - p1[0])
    lat = p1[1] + t * (p2[1] - p1[1])
    e1 = p1[2] if p1[2] is not None else 0.0
    e2 = p2[2] if p2[2] is not None else 0.0
    ele = e1 + t * (e2 - e1)
    return lon, lat, ele


def kilometre_markers(
    points: list[tuple[float, float, float | None]], step_km: float = 10.0
) -> list[tuple[float, float, float, float]]:
    """Return [(lon, lat, ele, km), ...] at every step_km along the track."""
    markers = []
    step_m = step_km * 1000
    cumul = 0.0
    next_mark = step_m  # first marker at step_km

    for i in range(1, len(points)):
        p0, p1 = points[i - 1], points[i]
        seg_len = haversine_m(p0[0], p0[1], p1[0], p1[1])
        while next_mark <= cumul + seg_len:
            t = (next_mark - cumul) / seg_len if seg_len > 0 else 0.0
            lon, lat, ele = interpolate(p0, p1, t)
            markers.append((lon, lat, ele, next_mark / 1000))
            next_mark += step_m
        cumul += seg_len

    return markers


def build_kml(
    track_name: str,
    points: list[tuple[float, float, float | None]],
    step_km: float = 10.0,
) -> str:
    coords_parts = []
    for lon, lat, ele in points:
        ele_val = ele if ele is not None else 0
        coords_parts.append(f"{lon},{lat},{ele_val}")
    coordinates = "\n".join(coords_parts)

    safe_name = re.sub(r"[&<>\"']", "", track_name)

    markers = kilometre_markers(points, step_km)
    markers_kml = "\n".join(
        f"""    <Placemark>
      <name>{km:.0f} km</name>
      <styleUrl>#markerStyle</styleUrl>
      <Point>
        <altitudeMode>absolute</altitudeMode>
        <coordinates>{lon},{lat},{ele:.0f}</coordinates>
      </Point>
    </Placemark>"""
        for lon, lat, ele, km in markers
    )

    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{safe_name}</name>
    <Style id="trackStyle">
      <LineStyle>
        <color>ff0000ff</color>
        <width>3</width>
      </LineStyle>
    </Style>
    <Style id="markerStyle">
      <IconStyle>
        <color>ff00ffff</color>
        <scale>0.8</scale>
        <Icon>
          <href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href>
        </Icon>
      </IconStyle>
      <LabelStyle>
        <scale>0.9</scale>
      </LabelStyle>
    </Style>
    <Placemark>
      <name>{safe_name}</name>
      <styleUrl>#trackStyle</styleUrl>
      <LineString>
        <tessellate>1</tessellate>
        <altitudeMode>absolute</altitudeMode>
        <coordinates>
{coordinates}
        </coordinates>
      </LineString>
    </Placemark>
{markers_kml}
  </Document>
</kml>"""
    return kml


def main():
    parser = argparse.ArgumentParser(description="Convert GPX track to KML or KMZ")
    parser.add_argument("input", nargs="?", default="gpx/parcours.gpx", help="Input GPX file")
    parser.add_argument("-o", "--output", help="Output file (.kml or .kmz); default: same name as input")
    parser.add_argument("--kmz", action="store_true", help="Force KMZ output (zipped KML)")
    parser.add_argument("--step", type=float, default=10.0, metavar="KM", help="Kilometre marker interval (default: 10)")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"File not found: {input_path}")

    if args.output:
        output_path = Path(args.output)
        use_kmz = output_path.suffix.lower() == ".kmz" or args.kmz
    else:
        suffix = ".kmz" if args.kmz else ".kml"
        output_path = input_path.with_suffix(suffix)
        use_kmz = args.kmz

    print(f"Parsing {input_path}...")
    track_name, points = parse_gpx(input_path)
    print(f"  Track: {track_name!r} — {len(points)} points")

    kml_content = build_kml(track_name, points, step_km=args.step)
    markers = kilometre_markers(points, args.step)
    print(f"  {len(markers)} markers every {args.step:.0f} km")

    if use_kmz:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("doc.kml", kml_content)
        print(f"Written {output_path} (KMZ)")
    else:
        output_path.write_text(kml_content, encoding="utf-8")
        print(f"Written {output_path} (KML)")


if __name__ == "__main__":
    main()
