"""
relay/gpx.py

Génère un fichier GPX ou KML à partir d'une Solution et d'un parcours GPX source.

GPX : un <trk> par relais + un <wpt> par borne de relais.
KML : un <Placemark> de ligne par relais (coloré par coureur, une Folder par
      coureur) + un <Placemark> de point par borne.

API publique :
  solution_to_gpx(solution, gpx_source, output_path)
  solution_to_kml(solution, gpx_source, output_path)
"""

import math
from pathlib import Path
import xml.etree.ElementTree as ET
from collections import defaultdict


_GPX_NS = "http://www.topografix.com/GPX/1/1"
_GPX_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<gpx version="1.1" creator="relais-planner"'
    ' xmlns="http://www.topografix.com/GPX/1/1"'
    ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
    ' xsi:schemaLocation="http://www.topografix.com/GPX/1/1'
    ' http://www.topografix.com/GPX/1/1/gpx.xsd">\n'
)


# ---------------------------------------------------------------------------
# Parsing du GPX source
# ---------------------------------------------------------------------------

def _parse_gpx_points(gpx_path: str) -> list[dict]:
    """Lit le premier <trkseg> du GPX source.

    Retourne une liste de dicts : lat, lon, ele (float|None), cum_km.
    """
    tree = ET.parse(gpx_path)
    root = tree.getroot()

    ns = _GPX_NS
    seg = root.find(f".//{{{ns}}}trkseg")
    if seg is None:
        seg = root.find(".//trkseg")
        ns = ""
    if seg is None:
        raise ValueError(f"Aucun <trkseg> trouvé dans {gpx_path}")

    tag_pt = f"{{{ns}}}trkpt" if ns else "trkpt"
    tag_ele = f"{{{ns}}}ele" if ns else "ele"

    points = []
    prev_lat = prev_lon = None
    cum_km = 0.0

    for pt in seg.findall(tag_pt):
        lat = float(pt.attrib["lat"])
        lon = float(pt.attrib["lon"])
        ele_el = pt.find(tag_ele)
        ele = float(ele_el.text) if ele_el is not None else None

        if prev_lat is not None:
            cum_km += _haversine_km(prev_lat, prev_lon, lat, lon)

        points.append({"lat": lat, "lon": lon, "ele": ele, "cum_km": cum_km})
        prev_lat, prev_lon = lat, lon

    return points


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Découpage de la trace entre deux km
# ---------------------------------------------------------------------------

def _find_nearest_idx(points: list[dict], km: float) -> int:
    best = 0
    best_d = abs(points[0]["cum_km"] - km)
    for i, p in enumerate(points):
        d = abs(p["cum_km"] - km)
        if d < best_d:
            best_d = d
            best = i
    return best


def _slice_points(points: list[dict], km_start: float, km_end: float) -> list[dict]:
    """Extrait les points GPX entre km_start et km_end (inclus, au moins 2 points)."""
    i_start = _find_nearest_idx(points, km_start)
    i_end = _find_nearest_idx(points, km_end)
    if i_start > i_end:
        i_start, i_end = i_end, i_start
    sliced = points[i_start: i_end + 1]
    if len(sliced) < 2:
        sliced = [points[i_start], points[i_end]]
    return sliced


# ---------------------------------------------------------------------------
# Coordonnées GPS d'un waypoint (depuis constraints.waypoints)
# ---------------------------------------------------------------------------

def _waypoint_gps(constraints, point_idx: int) -> tuple[float, float, float | None]:
    """Retourne (lat, lon, alt) pour un point de relais.

    Les coordonnées doivent être présentes dans constraints.waypoints (relay_points.json).
    Lève ValueError si lat/lon sont absents.
    """
    wp = constraints.waypoints[point_idx]
    lat = wp.get("lat")
    lon = wp.get("lon")
    if lat is None or lon is None:
        km = constraints.waypoints_km[point_idx]
        raise ValueError(
            f"Waypoint index {point_idx} (km={km:.2f}) sans coordonnées GPS (lat/lon). "
            "Le fichier relay_points.json doit contenir lat et lon pour chaque point."
        )
    return lat, lon, wp.get("alt")


# ---------------------------------------------------------------------------
# Waypoints aux bornes de relais
# ---------------------------------------------------------------------------

_JOURS = ["mer", "jeu", "ven", "sam", "dim", "lun", "mar"]


def _fmt_heure(h_abs: float) -> str:
    """Formate une heure absolue (depuis minuit j0) en '[jour heureHminute]'."""
    jour_idx = int(h_abs // 24)
    h_mod = h_abs % 24
    hh = int(h_mod)
    mm = round((h_mod - hh) * 60)
    if mm == 60:
        hh += 1
        mm = 0
    jour_str = _JOURS[jour_idx % len(_JOURS)]
    return f"[{jour_str} {hh:02d}h{mm:02d}]"


def _build_waypoints(relays: list[dict], constraints) -> list[dict]:
    """Construit un waypoint par borne de relais unique (point index).

    Retourne une liste de dicts : lat, lon, name, desc.
    """
    arriving: dict[int, list[str]] = defaultdict(list)
    departing: dict[int, list[str]] = defaultdict(list)
    relay_km_by_start: dict[int, float] = {}  # point → km du relais partant

    for r in relays:
        departing[r["start"]].append(r["runner"])
        arriving[r["end"]].append(r["runner"])
        relay_km_by_start.setdefault(r["start"], r["km"])

    all_points = sorted(set(arriving.keys()) | set(departing.keys()))

    wpts = []
    for pt in all_points:
        lat, lon, _ = _waypoint_gps(constraints, pt)
        km_val = constraints.waypoints_km[pt]
        km_str = f"{km_val:.1f} km"

        h_abs = constraints._point_hour(pt)
        heure_str = _fmt_heure(h_abs)

        arr = arriving.get(pt, [])
        dep = departing.get(pt, [])

        relay_km = relay_km_by_start.get(pt)
        relay_km_str = f"{relay_km:.1f} km" if relay_km is not None else ""

        desc_parts = []
        if relay_km_str:
            desc_parts.append(relay_km_str)
        desc_parts.append(f"Pt {pt}")
        if arr:
            desc_parts.append("Arrivée : " + ", ".join(sorted(arr)))
        if dep:
            desc_parts.append("Départ : " + ", ".join(sorted(dep)))

        wpts.append({
            "lat": lat,
            "lon": lon,
            "name": f"{km_str} - {heure_str}",
            "desc": " | ".join(desc_parts),
        })

    return wpts


# ---------------------------------------------------------------------------
# Génération GPX
# ---------------------------------------------------------------------------

def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _wpt_xml(w: dict) -> str:
    return (
        f'  <wpt lat="{w["lat"]:.6f}" lon="{w["lon"]:.6f}">\n'
        f'    <name>{_escape(w["name"])}</name>\n'
        f'    <desc>{_escape(w["desc"])}</desc>\n'
        f'  </wpt>\n'
    )


def _trk_xml(relay: dict, sliced: list[dict]) -> str:
    runner = relay["runner"]
    s = relay["start"]
    e = relay["end"]
    partner = relay.get("partner") or ""
    solo = relay.get("solo", False)
    km = relay.get("km", 0)

    if partner:
        trk_name = f"{runner} & {partner} – P{s}→P{e}"
    elif solo:
        trk_name = f"{runner} (solo) – P{s}→P{e}"
    else:
        trk_name = f"{runner} – P{s}→P{e}"

    desc = f"km {km:.2f} | pt {s}→{e}"
    if relay.get("d_plus"):
        desc += f" | D+ {relay['d_plus']:.0f}m"

    lines = [
         '  <trk>\n',
        f'    <name>{_escape(trk_name)}</name>\n',
        f'    <desc>{_escape(desc)}</desc>\n',
         '    <trkseg>\n',
    ]
    for p in sliced:
        ele = f"\n      <ele>{p['ele']:.1f}</ele>" if p["ele"] is not None else ""
        lines.append(
            f'      <trkpt lat="{p["lat"]:.6f}" lon="{p["lon"]:.6f}">{ele}\n'
            f'      </trkpt>\n'
        )
    lines.append('    </trkseg>\n  </trk>\n')
    return "".join(lines)


# ---------------------------------------------------------------------------
# KML — palette de couleurs
# ---------------------------------------------------------------------------

_PALETTE_RGB = [
    (0xe6, 0x19, 0x4b),
    (0x3c, 0xb4, 0x4b),
    (0x43, 0x63, 0xd8),
    (0xf5, 0x82, 0x31),
    (0x91, 0x1e, 0xb4),
    (0x42, 0xd4, 0xf4),
    (0xf0, 0x32, 0xe6),
    (0xbf, 0xef, 0x45),
    (0xfa, 0xbe, 0xd4),
    (0x46, 0x99, 0x90),
    (0xdc, 0xbe, 0xff),
    (0x80, 0x00, 0x00),
    (0xaa, 0xff, 0xc3),
    (0x80, 0x80, 0x00),
    (0xff, 0xd8, 0xb1),
    (0x00, 0x00, 0x75),
]

_ICON_URL = "http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png"


def _rgb_to_kml(r: int, g: int, b: int, alpha: int = 0xFF) -> str:
    return f"{alpha:02x}{b:02x}{g:02x}{r:02x}"


def _runner_color(idx: int) -> str:
    r, g, b = _PALETTE_RGB[idx % len(_PALETTE_RGB)]
    return _rgb_to_kml(r, g, b)


# ---------------------------------------------------------------------------
# KML — génération XML
# ---------------------------------------------------------------------------

def _kml_style_line(style_id: str, color: str, width: int = 3) -> str:
    return (
        f'  <Style id="{style_id}">\n'
        f'    <LineStyle><color>{color}</color><width>{width}</width></LineStyle>\n'
        f'    <PolyStyle><fill>0</fill></PolyStyle>\n'
        f'  </Style>\n'
    )


def _kml_style_marker(style_id: str, color: str) -> str:
    return (
        f'  <Style id="{style_id}">\n'
        f'    <IconStyle>\n'
        f'      <color>{color}</color>\n'
        f'      <scale>0.8</scale>\n'
        f'      <Icon><href>{_ICON_URL}</href></Icon>\n'
        f'    </IconStyle>\n'
        f'    <LabelStyle><scale>0.7</scale></LabelStyle>\n'
        f'  </Style>\n'
    )


def _kml_placemark_line(name: str, desc: str, style_id: str, coords: list[dict]) -> str:
    coord_str = "\n          ".join(
        f'{p["lon"]:.6f},{p["lat"]:.6f},{p.get("ele") or 0:.0f}'
        for p in coords
    )
    return (
        f'    <Placemark>\n'
        f'      <name>{_escape(name)}</name>\n'
        f'      <description>{_escape(desc)}</description>\n'
        f'      <styleUrl>#{style_id}</styleUrl>\n'
        f'      <LineString>\n'
        f'        <tessellate>1</tessellate>\n'
        f'        <coordinates>\n'
        f'          {coord_str}\n'
        f'        </coordinates>\n'
        f'      </LineString>\n'
        f'    </Placemark>\n'
    )


def _kml_placemark_point(w: dict, style_id: str) -> str:
    return (
        f'  <Placemark>\n'
        f'    <name>{_escape(w["name"])}</name>\n'
        f'    <description><![CDATA[{w["desc"]}]]></description>\n'
        f'    <styleUrl>#{style_id}</styleUrl>\n'
        f'    <Point><coordinates>{w["lon"]:.6f},{w["lat"]:.6f},0</coordinates></Point>\n'
        f'  </Placemark>\n'
    )


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------

def to_gpx(solution, gpx_source: str, output_path: str) -> None:
    """Génère un fichier GPX depuis une WaypointSolution et un parcours GPX source.

    Paramètres
    ----------
    solution    : relay.Solution
    gpx_source  : chemin vers le fichier GPX source (trace complète du parcours)
    output_path : chemin du fichier GPX à écrire
    """
    c = solution.constraints
    relays = solution.relays
    gpx_points = _parse_gpx_points(gpx_source)

    sorted_relays = sorted(relays, key=lambda r: (r["start"], r["runner"]))
    waypoints = _build_waypoints(relays, c)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(_GPX_HEADER)

        for w in waypoints:
            f.write(_wpt_xml(w))

        for relay in sorted_relays:
            km_start = c.waypoints_km[relay["start"]]
            km_end = c.waypoints_km[relay["end"]]
            sliced = _slice_points(gpx_points, km_start, km_end)
            f.write(_trk_xml(relay, sliced))

        f.write("</gpx>\n")


def to_kml(solution, gpx_source: str, output_path: str) -> None:
    """Génère un fichier KML depuis une WaypointSolution et un parcours GPX source.

    Paramètres
    ----------
    solution    : relay.Solution
    gpx_source  : chemin vers le fichier GPX source (trace complète du parcours)
    output_path : chemin du fichier KML à écrire
    """
    c = solution.constraints
    relays = solution.relays
    gpx_points = _parse_gpx_points(gpx_source)

    runners_ordered = sorted({r["runner"] for r in relays})
    runner_idx = {name: i for i, name in enumerate(runners_ordered)}

    by_runner: dict[str, list[dict]] = defaultdict(list)
    for r in sorted(relays, key=lambda r: r["start"]):
        by_runner[r["runner"]].append(r)

    waypoints = _build_waypoints(relays, c)
    marker_color = _rgb_to_kml(0x43, 0xa0, 0x47)  # vert unique (pas de type d'accès)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<kml xmlns="http://www.opengis.net/kml/2.2">\n')
        f.write('<Document>\n')
        f.write('  <name>Relais planner</name>\n')

        for name, idx in runner_idx.items():
            f.write(_kml_style_line(f"line_{idx}", _runner_color(idx)))

        f.write(_kml_style_marker("marker", marker_color))

        for runner in runners_ordered:
            idx = runner_idx[runner]
            f.write(f'  <Folder><name>{_escape(runner)}</name>\n')
            for relay in by_runner[runner]:
                km_start = c.waypoints_km[relay["start"]]
                km_end = c.waypoints_km[relay["end"]]
                sliced = _slice_points(gpx_points, km_start, km_end)

                s = relay["start"]
                e = relay["end"]
                partner = relay.get("partner") or ""
                solo = relay.get("solo", False)
                km = relay.get("km", 0)

                if partner:
                    name = f"{runner} &amp; {partner} – P{s}→P{e}"
                elif solo:
                    name = f"{runner} (solo) – P{s}→P{e}"
                else:
                    name = f"{runner} – P{s}→P{e}"
                desc = f"km {km:.2f} | pt {s}→{e}"
                if relay.get("d_plus"):
                    desc += f" | D+ {relay['d_plus']:.0f}m"

                f.write(_kml_placemark_line(name, desc, f"line_{idx}", sliced))
            f.write('  </Folder>\n')

        f.write('  <Folder><name>Points de passage</name>\n')
        for w in waypoints:
            f.write(_kml_placemark_point(w, "marker"))
        f.write('  </Folder>\n')

        f.write('</Document>\n</kml>\n')


def to_split(solution, gpx_source: str, outdir: str | Path, gpx: bool, kml:bool) -> None:
    """Exporte des fichiers GPX et KML partiels pour chaque relais.

    Crée une arborescence : outdir/runner/k.gpx et outdir/runner/k.kml
    où k est l'index de relais du coureur.

    Paramètres
    ----------
    solution    : relay.Solution
    gpx_source  : chemin vers le fichier GPX source (trace complète du parcours)
    outdir      : répertoire de sortie
    """
    outdir = Path(outdir)
    c = solution.constraints
    relays = solution.relays
    gpx_points = _parse_gpx_points(gpx_source)

    # Index relais par coureur
    by_runner = {}
    for relay in relays:
        runner = relay["runner"]
        if runner not in by_runner:
            by_runner[runner] = []
        by_runner[runner].append(relay)

    # Nettoyer les anciens fichiers split avant d'écrire les nouveaux
    # (garder seulement les fichiers de la dernière solution d'un run)
    if outdir.exists():
        for runner_dir in outdir.iterdir():
            if runner_dir.is_dir():
                for gpx_file in runner_dir.glob("*.gpx"):
                    gpx_file.unlink()
                for kml_file in runner_dir.glob("*.kml"):
                    kml_file.unlink()

    # Créer répertoires et exporter
    for runner, runner_relays in by_runner.items():
        runner_dir = outdir / runner
        runner_dir.mkdir(parents=True, exist_ok=True)

        for relay in sorted(runner_relays, key=lambda r: r["start"]):
            km_start = c.waypoints_km[relay["start"]]
            km_end = c.waypoints_km[relay["end"]]
            trace = _slice_points(gpx_points, km_start, km_end)
            # nom des fichiers générés
            avec_str = f"{relay["partner"]}" if relay["partner"] else "solo"
            ts = _fmt_heure(c._point_hour(relay["end"]))
            base_path = runner_dir / f"{ts} {runner} {avec_str}"

            if gpx:
                _to_gpx(c, str(base_path) + ".gpx", relay, trace )
            if kml:
                _to_kml(str(base_path) + ".kml",runner, relay, trace )


def _to_gpx(c, gpx_path:str, relay, trace ):
    with open(gpx_path, "w", encoding="utf-8") as f:
        f.write(_GPX_HEADER)

        # Waypoints de départ et d'arrivée
        try:
            lat_s, lon_s, alt_s = _waypoint_gps(c, relay["start"])
            lat_e, lon_e, alt_e = _waypoint_gps(c, relay["end"])

            f.write(f'  <wpt lat="{lat_s:.6f}" lon="{lon_s:.6f}">\n')
            f.write(f'    <name>Départ (Pt {relay["start"]})</name>\n')
            f.write('  </wpt>\n')

            f.write(f'  <wpt lat="{lat_e:.6f}" lon="{lon_e:.6f}">\n')
            f.write(f'    <name>Arrivée (Pt {relay["end"]})</name>\n')
            f.write('  </wpt>\n')
        except ValueError:
            pass  # Si coordonnées manquantes, skip waypoints

        # Track du relais
        f.write(_trk_xml(relay, trace))
        f.write("</gpx>\n")




def _to_kml(c, kml_path, runner, relay, trace):
    runner_idx = 0  # Couleur unique par fichier
    line_color = _runner_color(runner_idx)

    k = relay["k"]
    with open(kml_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<kml xmlns="http://www.opengis.net/kml/2.2">\n')
        f.write('<Document>\n')
        f.write(f'  <name>{_escape(runner)} - Relais {k}</name>\n')
        f.write(_kml_style_line("line_0", line_color))
        f.write('  <Style id="marker">\n')
        f.write('    <IconStyle>\n')
        f.write('      <color>ff43a047</color>\n')
        f.write('      <scale>0.8</scale>\n')
        f.write(f'      <Icon><href>{_ICON_URL}</href></Icon>\n')
        f.write('    </IconStyle>\n')
        f.write('    <LabelStyle><scale>0.7</scale></LabelStyle>\n')
        f.write('  </Style>\n')

        # Placemark de la ligne
        s = relay["start"]
        e = relay["end"]
        partner = relay.get("partner") or ""
        solo = relay.get("solo", False)
        km = relay.get("km", 0)

        if partner:
            name = f"{runner} &amp; {partner} – P{s}→P{e}"
        elif solo:
            name = f"{runner} (solo) – P{s}→P{e}"
        else:
            name = f"{runner} – P{s}→P{e}"
        desc = f"km {km:.2f} | pt {s}→{e}"
        if relay.get("d_plus"):
            desc += f" | D+ {relay['d_plus']:.0f}m"

        f.write(_kml_placemark_line(name, desc, "line_0", trace))

        # Waypoints
        try:
            lat_s, lon_s, _ = _waypoint_gps(c, relay["start"])
            lat_e, lon_e, _ = _waypoint_gps(c, relay["end"])

            f.write('  <Placemark>\n')
            f.write(f'    <name>Départ (Pt {relay["start"]})</name>\n')
            f.write('    <styleUrl>#marker</styleUrl>\n')
            f.write(f'    <Point><coordinates>{lon_s:.6f},{lat_s:.6f},0</coordinates></Point>\n')
            f.write('  </Placemark>\n')

            f.write('  <Placemark>\n')
            f.write(f'    <name>Arrivée (Pt {relay["end"]})</name>\n')
            f.write('    <styleUrl>#marker</styleUrl>\n')
            f.write(f'    <Point><coordinates>{lon_e:.6f},{lat_e:.6f},0</coordinates></Point>\n')
            f.write('  </Placemark>\n')
        except ValueError:
            pass

        f.write('</Document>\n</kml>\n')
