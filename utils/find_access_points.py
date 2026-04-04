"""
Calcul des points d'accès véhicule sur le parcours Lyon–Fessenheim.

Pour chaque jalon (frontière entre segments : km_start du segment i, plus le
km_end du dernier segment), cherche toutes les intersections géométriques
réelles entre la trace GPX et les routes OSM dans un rayon de DELTA_MAX_M
mètres. Retourne un enregistrement par croisement, avec la distance réelle
depuis le départ (km_cross) — matière première pour une optimisation LP des
points de relais.

Entrées :
  gpx/lyon-fessenheim-vdef-1.gpx   — parcours complet
  gpx/roads.json                   — routes OSM avec géométrie (out geom)

Sorties :
  gpx/access_points.csv         — un croisement par ligne
  gpx/access_points.gpx         — waypoints GPX
  gpx/access_points.html        — carte Leaflet interactive
"""

import csv
import json
import math
import os
import xml.etree.ElementTree as ET

# --- Configuration -----------------------------------------------------------

GPX_FILE = "gpx/lyon-fessenheim-vdef-1.gpx"
ROADS_FILE = "gpx/roads.json"
OUT_DIR = "gpx"

SEGMENT_KM = 2.5           # longueur d'un segment théorique (km)
DELTA_MAX_M = 1000           # rayon de recherche d'intersections autour d'une extrémité (m)
RADIUS_M = 300              # rayon de proximité pour la recherche de routes sans intersection (m)

# Priorité des types de route (plus bas = meilleur)
ROAD_PRIORITY = {
    "primary": 1, "primary_link": 1,
    "secondary": 2, "secondary_link": 2,
    "tertiary": 3, "tertiary_link": 3,
    "unclassified": 4,
    "residential": 5,
    "service": 6,
    "road": 7,
    "trunk": 8, "trunk_link": 8,
    "motorway": 9, "motorway_link": 9,
}

ACCEPTABLE_TYPES = {
    "primary", "primary_link",
    "secondary", "secondary_link",
    "tertiary", "tertiary_link",
    "unclassified", "residential", "service", "road",
}


# --- Lecture et échantillonnage du GPX ---------------------------------------

def parse_gpx(gpx_path):
    """Retourne la liste de tous les trkpt {lat, lon} du fichier GPX."""
    tree = ET.parse(gpx_path)
    root = tree.getroot()
    ns = {"gpx": "http://www.topografix.com/GPX/1/1"}
    pts = root.findall(".//gpx:trkpt", ns)
    return [{"lat": float(p.attrib["lat"]), "lon": float(p.attrib["lon"])} for p in pts]


def haversine(lat1, lon1, lat2, lon2):
    """Distance en mètres entre deux points (lat/lon en degrés)."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def build_track_with_cumdist(track_pts):
    """
    Ajoute à chaque point sa distance cumulée depuis le départ (en mètres).
    Retourne une nouvelle liste {lat, lon, cum_m}.
    """
    result = [{"lat": track_pts[0]["lat"], "lon": track_pts[0]["lon"], "cum_m": 0.0}]
    for p in track_pts[1:]:
        prev = result[-1]
        d = haversine(prev["lat"], prev["lon"], p["lat"], p["lon"])
        result.append({"lat": p["lat"], "lon": p["lon"], "cum_m": prev["cum_m"] + d})
    return result


def sample_segments(track, segment_km=SEGMENT_KM):
    """
    Échantillonne le parcours tous les segment_km km.

    `track` est la liste avec cum_m (sortie de build_track_with_cumdist).

    Retourne une liste de segments :
      segment               : indice 0-based
      km_start, km_end      : bornes théoriques (multiples de segment_km)
      lat_start, lon_start  : extrémité début (interpolée)
      lat_end,   lon_end    : extrémité fin (interpolée)
      cum_m_start, cum_m_end: distances cumulées réelles des extrémités (m)
    """
    threshold_m = segment_km * 1000
    segments = []
    seg_idx = 0

    # Extrémité de début du segment courant
    prev_jal = track[0].copy()   # {lat, lon, cum_m}
    next_mark_m = threshold_m

    for i in range(1, len(track)):
        p = track[i]
        while p["cum_m"] >= next_mark_m:
            prev = track[i - 1]
            span = p["cum_m"] - prev["cum_m"]
            t = (next_mark_m - prev["cum_m"]) / span if span > 0 else 0.0
            jal = {
                "lat": prev["lat"] + t * (p["lat"] - prev["lat"]),
                "lon": prev["lon"] + t * (p["lon"] - prev["lon"]),
                "cum_m": next_mark_m,
            }
            segments.append({
                "segment": seg_idx,
                "km_start": (next_mark_m - threshold_m) / 1000,
                "km_end": next_mark_m / 1000,
                "lat_start": prev_jal["lat"], "lon_start": prev_jal["lon"],
                "lat_end": jal["lat"],        "lon_end": jal["lon"],
                "cum_m_start": prev_jal["cum_m"],
                "cum_m_end": jal["cum_m"],
            })
            seg_idx += 1
            prev_jal = jal
            next_mark_m += threshold_m

    # Dernier segment partiel
    last = track[-1]
    if last["cum_m"] > prev_jal["cum_m"]:
        segments.append({
            "segment": seg_idx,
            "km_start": (next_mark_m - threshold_m) / 1000,
            "km_end": last["cum_m"] / 1000,
            "lat_start": prev_jal["lat"], "lon_start": prev_jal["lon"],
            "lat_end": last["lat"],       "lon_end": last["lon"],
            "cum_m_start": prev_jal["cum_m"],
            "cum_m_end": last["cum_m"],
        })

    return segments


# --- Géométrie ---------------------------------------------------------------

def _local_coords(ref_lat, ref_lon, cos_lat, lat, lon):
    return (lon - ref_lon) * cos_lat, lat - ref_lat


def segment_intersect(p1, p2, p3, p4):
    """
    Intersection de deux segments [P1,P2] et [P3,P4] dans un plan local.
    Retourne (t, u) avec t,u ∈ [0,1] si croisement, sinon None.
    t : paramètre sur [P1,P2] (côté trace GPX).
    """
    x1, y1 = p1; x2, y2 = p2; x3, y3 = p3; x4, y4 = p4
    dx1, dy1 = x2 - x1, y2 - y1
    dx2, dy2 = x4 - x3, y4 - y3
    denom = dx1 * dy2 - dy1 * dx2
    if abs(denom) < 1e-12:
        return None
    t = ((x3 - x1) * dy2 - (y3 - y1) * dx2) / denom
    u = ((x3 - x1) * dy1 - (y3 - y1) * dx1) / denom
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return t, u
    return None


# --- Calcul des intersections ------------------------------------------------

def find_crossings_near_endpoint(endpoint_lat, endpoint_lon,
                                 track, ways, radius_m=DELTA_MAX_M):
    """
    Retourne tous les croisements trace↔route dont le point d'intersection
    est dans radius_m mètres de (endpoint_lat, endpoint_lon).

    `track` est la liste avec cum_m.

    Chaque croisement retourné :
      km_cross    : distance réelle depuis le départ au point de croisement (km)
      dist_m      : distance du croisement à l'extrémité de segment (m)
      lat_cross, lon_cross : coordonnées du croisement sur la trace
      road_type, road_name, way_id
    """
    cos_lat = math.cos(math.radians(endpoint_lat))
    margin = radius_m / 111_000

    lat_min = endpoint_lat - margin
    lat_max = endpoint_lat + margin
    lon_min = endpoint_lon - margin / cos_lat if cos_lat > 1e-9 else endpoint_lon - margin
    lon_max = endpoint_lon + margin / cos_lat if cos_lat > 1e-9 else endpoint_lon + margin

    # Indices des points de trace dans la fenêtre (±1 pour ne pas rater les croisements)
    track_in_window = []
    for i, p in enumerate(track):
        if lat_min <= p["lat"] <= lat_max and lon_min <= p["lon"] <= lon_max:
            track_in_window += [max(0, i - 1), i, min(len(track) - 1, i + 1)]
    gpx_indices = sorted(set(track_in_window))

    gpx_segs = [(track[i], track[i + 1]) for i in gpx_indices if i + 1 < len(track)]
    if not gpx_segs:
        return []

    crossings = []
    for way in ways:
        htype = way["tags"].get("highway", "")
        if htype not in ACCEPTABLE_TYPES:
            continue
        geom = way.get("geometry", [])
        if len(geom) < 2:
            continue

        bounds = way.get("bounds")
        if bounds and (bounds["maxlat"] < lat_min or bounds["minlat"] > lat_max
                       or bounds["maxlon"] < lon_min or bounds["minlon"] > lon_max):
            continue

        for ga, gb in gpx_segs:
            cos_local = math.cos(math.radians((ga["lat"] + gb["lat"]) / 2))
            pa = _local_coords(ga["lat"], ga["lon"], cos_local, ga["lat"], ga["lon"])
            pb = _local_coords(ga["lat"], ga["lon"], cos_local, gb["lat"], gb["lon"])

            for j in range(len(geom) - 1):
                ra, rb = geom[j], geom[j + 1]
                pc = _local_coords(ga["lat"], ga["lon"], cos_local, ra["lat"], ra["lon"])
                pd = _local_coords(ga["lat"], ga["lon"], cos_local, rb["lat"], rb["lon"])

                hit = segment_intersect(pa, pb, pc, pd)
                if hit is None:
                    continue

                t, _ = hit
                cross_lat = ga["lat"] + t * (gb["lat"] - ga["lat"])
                cross_lon = ga["lon"] + t * (gb["lon"] - ga["lon"])
                cross_cum_m = ga["cum_m"] + t * (gb["cum_m"] - ga["cum_m"])

                dist = haversine(endpoint_lat, endpoint_lon, cross_lat, cross_lon)
                if dist > radius_m:
                    continue

                crossings.append({
                    "km_cross": cross_cum_m / 1000,
                    "dist_m": dist,
                    "lat_cross": cross_lat,
                    "lon_cross": cross_lon,
                    "road_type": htype,
                    "road_name": way["tags"].get("name") or way["tags"].get("ref") or "",
                    "way_id": way["id"],
                })

    # Dédoublonnage par way_id : garder le croisement le plus proche de l'extrémité
    best_by_way = {}
    for c in crossings:
        wid = c["way_id"]
        if wid not in best_by_way or c["dist_m"] < best_by_way[wid]["dist_m"]:
            best_by_way[wid] = c

    result = list(best_by_way.values())
    result.sort(key=lambda c: (ROAD_PRIORITY.get(c["road_type"], 99), c["dist_m"]))
    return result


def find_roads_near_endpoint(endpoint_lat, endpoint_lon, ways, radius_m=RADIUS_M):
    """
    Retourne les routes présentes dans radius_m mètres de (endpoint_lat, endpoint_lon),
    sans chercher d'intersection géométrique avec la trace.

    Utilisé comme recherche complémentaire quand aucune intersection n'est trouvée
    dans DELTA_MAX_M mètres.

    Retourne une liste de dicts :
      dist_m      : distance du point de la route le plus proche de l'extrémité (m)
      lat_near, lon_near : coordonnées du point de route le plus proche
      road_type, road_name, way_id
    """
    cos_lat = math.cos(math.radians(endpoint_lat))
    margin = radius_m / 111_000

    lat_min = endpoint_lat - margin
    lat_max = endpoint_lat + margin
    lon_min = endpoint_lon - margin / cos_lat if cos_lat > 1e-9 else endpoint_lon - margin
    lon_max = endpoint_lon + margin / cos_lat if cos_lat > 1e-9 else endpoint_lon + margin

    best_by_way = {}
    for way in ways:
        htype = way["tags"].get("highway", "")
        if htype not in ACCEPTABLE_TYPES:
            continue
        geom = way.get("geometry", [])
        if not geom:
            continue

        bounds = way.get("bounds")
        if bounds and (bounds["maxlat"] < lat_min or bounds["minlat"] > lat_max
                       or bounds["maxlon"] < lon_min or bounds["minlon"] > lon_max):
            continue

        for node in geom:
            if not (lat_min <= node["lat"] <= lat_max and lon_min <= node["lon"] <= lon_max):
                continue
            dist = haversine(endpoint_lat, endpoint_lon, node["lat"], node["lon"])
            if dist > radius_m:
                continue
            wid = way["id"]
            if wid not in best_by_way or dist < best_by_way[wid]["dist_m"]:
                best_by_way[wid] = {
                    "dist_m": dist,
                    "lat_near": node["lat"],
                    "lon_near": node["lon"],
                    "road_type": htype,
                    "road_name": way["tags"].get("name") or way["tags"].get("ref") or "",
                    "way_id": wid,
                }

    result = list(best_by_way.values())
    result.sort(key=lambda r: (ROAD_PRIORITY.get(r["road_type"], 99), r["dist_m"]))
    return result


def _build_waypoints(segments):
    """
    Construit la liste des jalons (frontières de segments) sans doublon.
    Jalon i  →  km_start du segment i   (i = 0 .. N-1)
    Jalon N  →  km_end du dernier segment
    Retourne une liste de dicts {jalon, km, lat, lon}.
    """
    wps = []
    for seg in segments:
        wps.append({
            "jalon": seg["segment"],
            "km":    seg["km_start"],
            "lat":   seg["lat_start"],
            "lon":   seg["lon_start"],
        })
    last = segments[-1]
    wps.append({
        "jalon": last["segment"] + 1,
        "km":    last["km_end"],
        "lat":   last["lat_end"],
        "lon":   last["lon_end"],
    })
    return wps


def compute_all_crossings(segments, ways, track):
    """
    Pour chaque jalon (frontière entre segments), retourne tous les croisements
    trace↔route dans DELTA_MAX_M mètres, dédoublonnés.

    Retourne une liste plate de dicts triée par km_cross :
      jalon, km_boundary, km_cross, delta_km,
      dist_m, lat_cross, lon_cross, road_type, road_name, way_id, acces
    """
    waypoints = _build_waypoints(segments)
    raw = []
    n = len(waypoints)
    for i, wp in enumerate(waypoints):
        if i % 20 == 0:
            print(f"  Jalon {i}/{n}...")

        crossings = find_crossings_near_endpoint(wp["lat"], wp["lon"], track, ways)
        if crossings:
            for c in crossings:
                raw.append({
                    "jalon":       wp["jalon"],
                    "km_boundary": wp["km"],
                    "km_cross":    c["km_cross"],
                    "delta_km":    c["km_cross"] - wp["km"],
                    "dist_m":      c["dist_m"],
                    "lat_cross":   c["lat_cross"],
                    "lon_cross":   c["lon_cross"],
                    "road_type":   c["road_type"],
                    "road_name":   c["road_name"],
                    "way_id":      c["way_id"],
                    "acces":       "cross",
                })
        else:
            # Pas d'intersection : recherche de routes proches sans croisement
            nearby = find_roads_near_endpoint(wp["lat"], wp["lon"], ways)
            if nearby:
                for r in nearby:
                    raw.append({
                        "jalon":       wp["jalon"],
                        "km_boundary": wp["km"],
                        "km_cross":    wp["km"],
                        "delta_km":    0.0,
                        "dist_m":      r["dist_m"],
                        "lat_cross":   r["lat_near"],
                        "lon_cross":   r["lon_near"],
                        "road_type":   r["road_type"],
                        "road_name":   r["road_name"],
                        "way_id":      r["way_id"],
                        "acces":       "near",
                    })
            else:
                # Inaccessible : point d'accès sur le jalon théorique
                raw.append({
                    "jalon":       wp["jalon"],
                    "km_boundary": wp["km"],
                    "km_cross":    wp["km"],
                    "delta_km":    0.0,
                    "dist_m":      0.0,
                    "lat_cross":   wp["lat"],
                    "lon_cross":   wp["lon"],
                    "road_type":   "",
                    "road_name":   "",
                    "way_id":      None,
                    "acces":       "",
                })

    # Dédoublonnage : (way_id, km_cross au mètre près) → garder le plus proche
    dedup = {}
    for r in raw:
        key = (r["way_id"], round(r["km_cross"] * 1000))
        if key not in dedup or r["dist_m"] < dedup[key]["dist_m"]:
            dedup[key] = r

    results = sorted(dedup.values(), key=lambda r: r["km_cross"])
    return results


# --- Statistiques ------------------------------------------------------------

def print_stats(crossings, segments):
    """
    Affiche des statistiques sur la couverture des jalons :
      - Points inaccessibles (isolés, 2 consécutifs, plus de 2 consécutifs)
      - Points avec croisement : nb, |delta_km| moyen, top 5 par dist_m
      - Points sans croisement avec route à proximité : nb, dist_m moyen, top 5
    """
    n_jalons = len(segments) + 1   # jalons 0 .. N

    # Meilleure entrée par jalon, par catégorie
    best_cross = {}   # jalon → entrée acces="cross" (dist_m min)
    best_near  = {}   # jalon → entrée acces="near"  (dist_m min)

    for c in crossings:
        j = c["jalon"]
        if c.get("acces") == "cross":
            if j not in best_cross or c["dist_m"] < best_cross[j]["dist_m"]:
                best_cross[j] = c
        elif c.get("acces") == "near":
            if j not in best_near or c["dist_m"] < best_near[j]["dist_m"]:
                best_near[j] = c

    covered_cross = set(best_cross)
    covered_near  = set(best_near) - covered_cross
    best_near = {j: v for j, v in best_near.items() if j in covered_near}

    all_jalons   = set(range(n_jalons))
    inacc_jalons = sorted(all_jalons - covered_cross - covered_near)

    # Grouper les jalons inaccessibles consécutifs
    runs = []
    if inacc_jalons:
        run = [inacc_jalons[0]]
        for j in inacc_jalons[1:]:
            if j == run[-1] + 1:
                run.append(j)
            else:
                runs.append(run)
                run = [j]
        runs.append(run)

    isolated    = [r[0] for r in runs if len(r) == 1]
    double_runs = [r     for r in runs if len(r) == 2]
    long_runs   = [r     for r in runs if len(r) >  2]

    print("\n" + "=" * 60)
    print("STATISTIQUES DES POINTS DE RELAIS")
    print("=" * 60)
    print(f"\nJalons totaux : {n_jalons}")

    # --- Inaccessibles ---
    print(f"\n── Inaccessibles : {len(inacc_jalons)} / {n_jalons}")
    print(f"   Isolés                     : {len(isolated)}"
          + (f"  → {isolated[:5]}{' ...' if len(isolated) > 5 else ''}" if isolated else ""))
    print(f"   Doubles consécutifs        : {len(double_runs)}"
          + (f"  → {[r[0] for r in double_runs[:5]]}{' ...' if len(double_runs) > 5 else ''}"
             if double_runs else ""))
    print(f"   Runs > 2 consécutifs       : {len(long_runs)}"
          + (f"  → {[r[0] for r in long_runs[:5]]}{' ...' if len(long_runs) > 5 else ''}"
             if long_runs else ""))

    # --- Avec croisement ---
    cross_list = list(best_cross.values())
    if cross_list:
        avg_delta = sum(abs(c["delta_km"]) for c in cross_list) / len(cross_list)
        top10 = sorted(cross_list, key=lambda c: c["dist_m"], reverse=True)[:10]
    else:
        avg_delta, top10 = 0.0, []

    print(f"\n── Avec croisement : {len(covered_cross)} / {n_jalons}")
    print(f"   |Δkm| moyen : {avg_delta:.3f} km")
    if top10:
        print("   Top 10 (plus éloignés du jalon) :")
        for c in top10:
            name = c["road_name"] or "(sans nom)"
            print(f"     jalon {c['jalon']:3d}  km {c['km_boundary']:.2f}"
                  f"  dist {c['dist_m']:.0f} m  Δkm {c['delta_km']:+.3f}"
                  f"  {c['road_type']}  {name}")

    # --- Proximité sans croisement ---
    near_list = list(best_near.values())
    if near_list:
        avg_dist = sum(c["dist_m"] for c in near_list) / len(near_list)
        top10_near = sorted(near_list, key=lambda c: c["dist_m"], reverse=True)[:10]
    else:
        avg_dist, top10_near = 0.0, []

    print(f"\n── Sans croisement, route à proximité ({RADIUS_M} m) : {len(covered_near)} / {n_jalons}")
    print(f"   dist_m moyen : {avg_dist:.0f} m")
    if top10_near:
        print("   Top 10 (plus éloignées du jalon) :")
        for c in top10_near:
            name = c["road_name"] or "(sans nom)"
            print(f"     jalon {c['jalon']:3d}  km {c['km_boundary']:.2f}"
                  f"  dist {c['dist_m']:.0f} m  {c['road_type']}  {name}")

    print("=" * 60)


# --- Sorties -----------------------------------------------------------------

def write_csv(crossings, output_path):
    fieldnames = [
        "jalon", "km_boundary", "km_cross", "delta_km",
        "dist_m", "acces", "road_type", "road_name", "way_id",
        "lat_cross", "lon_cross",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(crossings)
    print(f"CSV écrit : {output_path} ({len(crossings)} croisements)")


ACCES_COLORS = {
    "cross": "#2ecc71",   # vert
    "near":  "#e67e22",   # orange
    "":      "#e74c3c",   # rouge (inaccessible)
}


def write_gpx(crossings, output_path):
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="find_access_points"'
        ' xmlns="http://www.topografix.com/GPX/1/1">',
    ]
    for c in crossings:
        name = f"km {c['km_cross']:.2f} (jalon {c['jalon']})"
        if c["road_name"]:
            name += f" – {c['road_name']}"
        desc = (f"{c['road_type']}, Δkm={c['delta_km']:+.3f},"
                f" {c['dist_m']:.0f} m du jalon")
        lines.append(
            f'  <wpt lat="{c["lat_cross"]:.7f}" lon="{c["lon_cross"]:.7f}">'
            f'<name>{name}</name><desc>{desc}</desc></wpt>'
        )
    lines.append("</gpx>")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"GPX écrit : {output_path} ({len(crossings)} waypoints)")


def write_html(crossings, segments, output_path, track_pts=None):
    # Trace GPX complète
    if track_pts:
        trace_coords = [[p["lat"], p["lon"]] for p in track_pts]
    else:
        trace_coords = []
        for seg in segments:
            if not trace_coords:
                trace_coords.append([seg["lat_start"], seg["lon_start"]])
            trace_coords.append([seg["lat_end"], seg["lon_end"]])

    # Marqueurs : un cercle par croisement
    markers_js = []
    for c in crossings:
        color = ACCES_COLORS.get(c.get("acces", ""), "#888")
        road_name = c["road_name"] or "(sans nom)"
        near_label = " [proximité]" if c.get("acces") == "near" else (
            " [inaccessible]" if not c.get("acces") else ""
        )
        popup = (
            f"Jalon {c['jalon']}{near_label}<br>"
            f"km jalon : {c['km_boundary']:.2f}<br>"
            f"km réel : {c['km_cross']:.2f} (Δ {c['delta_km']:+.3f})<br>"
            f"{road_name}<br>"
            f"Type : {c['road_type']}<br>"
            f"Distance jalon : {c['dist_m']:.0f} m"
        )
        markers_js.append(
            f'L.circleMarker([{c["lat_cross"]:.6f},{c["lon_cross"]:.6f}],'
            f'{{radius:5,color:"{color}",fillColor:"{color}",fillOpacity:0.85}})'
            f'.bindPopup("{popup}").addTo(map);'
        )

    # Jalons théoriques
    endpoints_js = []
    for wp in _build_waypoints(segments):
        j, km = wp["jalon"], wp["km"]
        endpoints_js.append(
            f'L.circleMarker([{wp["lat"]:.6f},{wp["lon"]:.6f}],'
            f'{{radius:3,color:"#2980b9",fillColor:"#2980b9",fillOpacity:0.5,'
            f'weight:1}})'
            f'.bindPopup("Jalon {j}<br>km {km:.2f}").addTo(map);'
        )

    markers_str = "\n    ".join(markers_js)
    endpoints_str = "\n    ".join(endpoints_js)
    trace_str = json.dumps(trace_coords)

    legend_items = "".join(
        f'<div><span style="background:{c};display:inline-block;width:12px;height:12px;'
        f'border-radius:50%;margin-right:4px"></span>{t}</div>'
        for t, c in [
            ("croisement", "#2ecc71"),
            ("intersection proche", "#e67e22"),
            ("inaccessible", "#e74c3c"),
            ("jalon théorique", "#2980b9"),
        ]
    )

    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="referrer" content="no-referrer-when-downgrade">
<title>Points d'accès v2 – Lyon–Fessenheim</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  body {{margin:0;padding:0}}
  #map {{height:100vh}}
  #legend {{
    position:absolute;bottom:30px;right:10px;z-index:1000;
    background:white;padding:10px;border-radius:6px;
    box-shadow:0 1px 5px rgba(0,0,0,0.4);font-size:12px;
  }}
</style>
</head><body>
<div id="map"></div>
<div id="legend"><b>Type de route</b><br>{legend_items}</div>
<script>
  var map = L.map('map').setView([46.8, 6.2], 8);
  L.tileLayer('https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png',
    {{attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors © <a href="https://carto.com/attributions">CARTO</a>',
     subdomains:'abcd', maxZoom:19}}).addTo(map);

  var trace = {trace_str};
  L.polyline(trace, {{color:'#2980b9',weight:3,opacity:0.7}}).addTo(map);

  {endpoints_str}
  {markers_str}
</script>
</body></html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML écrit : {output_path} ({len(markers_js)} croisements, {len(endpoints_js)} extrémités)")


# --- Main --------------------------------------------------------------------

def main():
    print(f"Lecture du GPX : {GPX_FILE}")
    track_pts = parse_gpx(GPX_FILE)
    print(f"  {len(track_pts)} points GPS")

    track = build_track_with_cumdist(track_pts)
    segments = sample_segments(track, segment_km=SEGMENT_KM)
    total_km = segments[-1]["km_end"] if segments else 0
    print(f"  {len(segments)} segments de {SEGMENT_KM} km ({total_km:.1f} km total)")

    print(f"\nChargement des routes : {ROADS_FILE}")
    with open(ROADS_FILE, encoding="utf-8") as f:
        roads = json.load(f)
    ways = [e for e in roads["elements"] if e["type"] == "way" and "geometry" in e]
    print(f"  {len(ways)} ways avec géométrie")

    print(f"\nRecherche des intersections dans {DELTA_MAX_M} m autour des extrémités...")
    crossings = compute_all_crossings(segments, ways, track)

    jalons_with_crossing = len({c["jalon"] for c in crossings})
    print(f"  {len(crossings)} croisements sur {jalons_with_crossing} jalons")

    print_stats(crossings, segments)

    print("\nGénération des sorties...")
    os.makedirs(OUT_DIR, exist_ok=True)
    write_csv(crossings, os.path.join(OUT_DIR, "access_points.csv"))
    write_gpx(crossings, os.path.join(OUT_DIR, "access_points.gpx"))
    write_html(crossings, segments, os.path.join(OUT_DIR, "access_points.html"),
               track_pts=track_pts)

    print("\nTerminé.")


if __name__ == "__main__":
    main()
