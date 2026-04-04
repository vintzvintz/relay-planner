"""
relay/gpx.py

Génère un fichier GPX ou KML à partir d'une Solution et d'un parcours GPX source.

GPX : un <trk> par relais + un <wpt> par borne de relais.
KML : un <Placemark> de ligne par relais (coloré par coureur, une Folder par
      coureur) + un <Placemark> de point par borne (coloré selon le type
      d'accès : vert=cross, orange=near, rouge=None).

API publique :
  solution_to_gpx(solution, gpx_source, output_path)
  solution_to_kml(solution, gpx_source, output_path)
"""

import xml.etree.ElementTree as ET
import math
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
    """
    Lit le premier <trkseg> du GPX source.

    Retourne une liste de dicts :
      lat, lon, ele (float|None), cum_km (distance cumulée depuis le départ)
    """
    tree = ET.parse(gpx_path)
    root = tree.getroot()

    # gère namespace explicite ou absent
    ns = _GPX_NS
    seg = root.find(f".//{{{ns}}}trkseg")
    if seg is None:
        # essai sans namespace
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


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Découpage de la trace
# ---------------------------------------------------------------------------

def _find_nearest_idx(points: list[dict], km: float) -> int:
    """Index du point GPX dont cum_km est le plus proche de km."""
    best = 0
    best_d = abs(points[0]["cum_km"] - km)
    for i, p in enumerate(points):
        d = abs(p["cum_km"] - km)
        if d < best_d:
            best_d = d
            best = i
    return best


def _slice_points(
    points: list[dict], km_start: float, km_end: float
) -> list[dict]:
    """
    Extrait les points GPX entre km_start et km_end (inclus).
    Garantit au moins 2 points (début + fin).
    """
    i_start = _find_nearest_idx(points, km_start)
    i_end = _find_nearest_idx(points, km_end)

    if i_start > i_end:
        i_start, i_end = i_end, i_start

    sliced = points[i_start : i_end + 1]
    if len(sliced) < 2:
        # dégénéré : retourne au moins les deux bornes
        sliced = [points[i_start], points[i_end]]
    return sliced


# ---------------------------------------------------------------------------
# Waypoints aux points de passage
# ---------------------------------------------------------------------------

def _build_waypoints(
    relays: list[dict],
    constraints,
    points: list[dict],
) -> list[dict]:
    """
    Construit un waypoint par borne de relais unique (segment actif).

    Pour chaque borne (segment actif s) :
      - position GPS : start_acces/end_acces si disponible, sinon point GPX le plus proche
      - nom : "Seg <s>" ou km réel
      - description : km, numéro segment, coureurs arrivants / partants

    Retourne une liste de dicts :
      lat, lon, name, desc
    """
    segment_km = constraints.total_km / constraints.nb_active_segments

    # Récolte les coureurs arrivants et partants à chaque borne active
    arriving: dict[int, list[str]] = defaultdict(list)   # segment actif → coureurs qui finissent ici
    departing: dict[int, list[str]] = defaultdict(list)  # segment actif → coureurs qui commencent ici
    acces_by_seg: dict[int, dict | None] = {}            # segment actif → access point dict

    def to_active(seg):
        if hasattr(constraints, "time_seg_to_active"):
            return constraints.time_seg_to_active(seg)
        return seg

    for r in relays:
        s = to_active(r["start"])
        e = to_active(r["end"])
        departing[s].append(r["runner"])
        arriving[e].append(r["runner"])
        if r.get("start_acces"):
            acces_by_seg[s] = r["start_acces"]
        if r.get("end_acces"):
            acces_by_seg[e] = r["end_acces"]

    all_segs = sorted(set(arriving.keys()) | set(departing.keys()))

    wpts = []
    for seg in all_segs:
        ap = acces_by_seg.get(seg)
        if ap is not None:
            lat = ap["lat"]
            lon = ap["lon"]
            km_val = ap["km_cross"]
        else:
            km_val = seg * segment_km
            idx = _find_nearest_idx(points, km_val)
            lat = points[idx]["lat"]
            lon = points[idx]["lon"]

        arr = arriving.get(seg, [])
        dep = departing.get(seg, [])
        km_str = f"{km_val:.1f} km"
        parts = [f"Seg {seg}", km_str]
        if arr:
            parts.append("Arrivée : " + ", ".join(sorted(arr)))
        if dep:
            parts.append("Départ : " + ", ".join(sorted(dep)))

        name = f"S{seg} – {km_str}"
        desc = " | ".join(parts)
        wpts.append({"lat": lat, "lon": lon, "name": name, "desc": desc})

    return wpts


# ---------------------------------------------------------------------------
# Génération XML
# ---------------------------------------------------------------------------

def _ele_str(ele) -> str:
    return f"<ele>{ele:.1f}</ele>" if ele is not None else ""


def _wpt_xml(w: dict) -> str:
    return (
        f'  <wpt lat="{w["lat"]:.6f}" lon="{w["lon"]:.6f}">\n'
        f'    <name>{_escape(w["name"])}</name>\n'
        f'    <desc>{_escape(w["desc"])}</desc>\n'
        f'  </wpt>\n'
    )


def _trk_xml(relay: dict, sliced: list[dict]) -> str:
    runner = relay["runner"]
    seg_start = relay["start"]
    seg_end = relay["end"]
    partner = relay.get("partner") or ""
    solo = relay.get("solo", False)
    km = relay.get("km", 0)

    if partner:
        trk_name = f"{runner} & {partner} – S{seg_start}→S{seg_end}"
    elif solo:
        trk_name = f"{runner} (solo) – S{seg_start}→S{seg_end}"
    else:
        trk_name = f"{runner} – S{seg_start}→S{seg_end}"

    desc = f"km {km:.2f} | seg {seg_start}→{seg_end}"
    if relay.get("d_plus"):
        desc += f" | D+ {relay['d_plus']:.0f}m"

    lines = [
        f'  <trk>\n',
        f'    <name>{_escape(trk_name)}</name>\n',
        f'    <desc>{_escape(desc)}</desc>\n',
        f'    <trkseg>\n',
    ]
    for p in sliced:
        ele = f"\n      <ele>{p['ele']:.1f}</ele>" if p["ele"] is not None else ""
        lines.append(
            f'      <trkpt lat="{p["lat"]:.6f}" lon="{p["lon"]:.6f}">{ele}\n'
            f'      </trkpt>\n'
        )
    lines.append('    </trkseg>\n  </trk>\n')
    return "".join(lines)


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ---------------------------------------------------------------------------
# KML — palette de couleurs
# ---------------------------------------------------------------------------

# Palette de couleurs distinctes (format KML : aabbggrr)
_PALETTE_RGB = [
    (0xe6, 0x19, 0x4b),  # rouge vif
    (0x3c, 0xb4, 0x4b),  # vert
    (0x43, 0x63, 0xd8),  # bleu
    (0xf5, 0x82, 0x31),  # orange
    (0x91, 0x1e, 0xb4),  # violet
    (0x42, 0xd4, 0xf4),  # cyan
    (0xf0, 0x32, 0xe6),  # magenta
    (0xbf, 0xef, 0x45),  # citron
    (0xfa, 0xbe, 0xd4),  # rose pâle
    (0x46, 0x99, 0x90),  # teal
    (0xdc, 0xbe, 0xff),  # lavande
    (0x80, 0x00, 0x00),  # bordeaux
    (0xaa, 0xff, 0xc3),  # menthe
    (0x80, 0x80, 0x00),  # olive
    (0xff, 0xd8, 0xb1),  # pêche
    (0x00, 0x00, 0x75),  # navy
]


def _rgb_to_kml(r: int, g: int, b: int, alpha: int = 0xFF) -> str:
    """Convertit RGB en couleur KML (aabbggrr)."""
    return f"{alpha:02x}{b:02x}{g:02x}{r:02x}"


def _runner_color(idx: int) -> str:
    r, g, b = _PALETTE_RGB[idx % len(_PALETTE_RGB)]
    return _rgb_to_kml(r, g, b)


# Couleurs des marqueurs selon le type d'accès
_MARKER_COLOR = {
    "cross": _rgb_to_kml(0x2e, 0xcc, 0x40),   # vert
    "near":  _rgb_to_kml(0xff, 0x85, 0x1b),   # orange
    None:    _rgb_to_kml(0xff, 0x41, 0x36),   # rouge
}

# URLs icônes Google (cercles colorés, compatibles Google Earth + Mes Cartes)
_ICON_URL = "http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png"


# ---------------------------------------------------------------------------
# KML — construction des waypoints enrichis (avec type d'accès)
# ---------------------------------------------------------------------------

def _build_waypoints_kml(
    relays: list[dict],
    constraints,
    points: list[dict],
) -> list[dict]:
    """
    Comme _build_waypoints mais ajoute le champ 'acces_type' (cross/near/None)
    pour la colorisation KML.
    """
    segment_km = constraints.total_km / constraints.nb_active_segments

    arriving: dict[int, list[str]] = defaultdict(list)
    departing: dict[int, list[str]] = defaultdict(list)
    acces_by_seg: dict[int, dict | None] = {}

    def to_active(seg):
        if hasattr(constraints, "time_seg_to_active"):
            return constraints.time_seg_to_active(seg)
        return seg

    for r in relays:
        s = to_active(r["start"])
        e = to_active(r["end"])
        departing[s].append(r["runner"])
        arriving[e].append(r["runner"])
        # start_acces peut être None explicitement (clé présente, valeur None)
        if "start_acces" in r:
            acces_by_seg.setdefault(s, r["start_acces"])
        if "end_acces" in r:
            acces_by_seg.setdefault(e, r["end_acces"])

    all_segs = sorted(set(arriving.keys()) | set(departing.keys()))

    wpts = []
    for seg in all_segs:
        ap = acces_by_seg.get(seg)
        if ap is not None:
            lat = ap["lat"]
            lon = ap["lon"]
            km_val = ap["km_cross"]
            acces_type = ap.get("acces")  # "cross", "near", ou None
        else:
            km_val = seg * segment_km
            idx = _find_nearest_idx(points, km_val)
            lat = points[idx]["lat"]
            lon = points[idx]["lon"]
            acces_type = None

        arr = arriving.get(seg, [])
        dep = departing.get(seg, [])
        km_str = f"{km_val:.1f} km"

        name = f"S{seg} – {km_str}"
        desc_parts = [f"Segment : {seg}", f"km : {km_val:.2f}"]
        if arr:
            desc_parts.append("Arrivée : " + ", ".join(sorted(arr)))
        if dep:
            desc_parts.append("Départ : " + ", ".join(sorted(dep)))
        if ap and ap.get("road_name"):
            desc_parts.append(f"Voie : {ap['road_name']}")

        wpts.append({
            "lat": lat,
            "lon": lon,
            "name": name,
            "desc": "<br>".join(desc_parts),
            "acces_type": acces_type,
        })

    return wpts


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
        f'{p["lon"]:.6f},{p["lat"]:.6f},{p["ele"] or 0:.0f}'
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

def solution_to_kml(solution, gpx_source: str, output_path: str) -> None:
    """
    Génère un fichier KML depuis une Solution et un parcours GPX source.

    Paramètres
    ----------
    solution    : relay.Solution
    gpx_source  : chemin vers le fichier GPX source (une seule trk/trkseg)
    output_path : chemin du fichier KML à écrire
    """
    constraints = solution.constraints
    relays = solution.relays

    points = _parse_gpx_points(gpx_source)
    segment_km = constraints.total_km / constraints.nb_active_segments

    def to_active(seg):
        if hasattr(constraints, "time_seg_to_active"):
            return constraints.time_seg_to_active(seg)
        return seg

    # Index coureur → couleur
    runners_ordered = sorted({r["runner"] for r in relays})
    runner_idx = {name: i for i, name in enumerate(runners_ordered)}

    # Regroupe les relais par coureur, triés par position
    by_runner: dict[str, list[dict]] = defaultdict(list)
    for r in sorted(relays, key=lambda r: to_active(r["start"])):
        by_runner[r["runner"]].append(r)

    waypoints = _build_waypoints_kml(relays, constraints, points)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<kml xmlns="http://www.opengis.net/kml/2.2">\n')
        f.write('<Document>\n')
        f.write(f'  <name>Relais planner</name>\n')

        # Styles lignes (un par coureur)
        for name, idx in runner_idx.items():
            color = _runner_color(idx)
            f.write(_kml_style_line(f"line_{idx}", color))

        # Styles marqueurs (un par type d'accès)
        for acces_key, color in _MARKER_COLOR.items():
            style_id = f"marker_{acces_key or 'none'}"
            f.write(_kml_style_marker(style_id, color))

        # Folder par coureur avec ses tracks
        for runner in runners_ordered:
            idx = runner_idx[runner]
            f.write(f'  <Folder><name>{_escape(runner)}</name>\n')
            for relay in by_runner[runner]:
                s = to_active(relay["start"])
                e = to_active(relay["end"])
                ap_start = relay.get("start_acces")
                ap_end = relay.get("end_acces")
                km_start = ap_start["km_cross"] if ap_start else s * segment_km
                km_end = ap_end["km_cross"] if ap_end else e * segment_km

                sliced = _slice_points(points, km_start, km_end)

                partner = relay.get("partner") or ""
                solo = relay.get("solo", False)
                km = relay.get("km", 0)
                if partner:
                    name = f"{runner} &amp; {partner} – S{s}→S{e}"
                elif solo:
                    name = f"{runner} (solo) – S{s}→S{e}"
                else:
                    name = f"{runner} – S{s}→S{e}"
                desc = f"km {km:.2f} | seg {s}→{e}"
                if relay.get("d_plus"):
                    desc += f" | D+ {relay['d_plus']:.0f}m"

                f.write(_kml_placemark_line(name, desc, f"line_{idx}", sliced))
            f.write('  </Folder>\n')

        # Folder points de passage
        f.write('  <Folder><name>Points de passage</name>\n')
        for w in waypoints:
            acces_type = w["acces_type"]
            style_id = f"marker_{acces_type or 'none'}"
            f.write(_kml_placemark_point(w, style_id))
        f.write('  </Folder>\n')

        f.write('</Document>\n</kml>\n')


def solution_to_gpx(solution, gpx_source: str, output_path: str) -> None:
    """
    Génère un fichier GPX depuis une Solution et un parcours GPX source.

    Paramètres
    ----------
    solution    : relay.Solution
    gpx_source  : chemin vers le fichier GPX source (une seule trk/trkseg)
    output_path : chemin du fichier GPX à écrire
    """
    constraints = solution.constraints
    relays = solution.relays

    points = _parse_gpx_points(gpx_source)
    segment_km = constraints.total_km / constraints.nb_active_segments

    def to_active(seg):
        if hasattr(constraints, "time_seg_to_active"):
            return constraints.time_seg_to_active(seg)
        return seg

    # Trie les relais par position de départ
    sorted_relays = sorted(relays, key=lambda r: (to_active(r["start"]), r["runner"]))

    waypoints = _build_waypoints(relays, constraints, points)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(_GPX_HEADER)

        # Waypoints d'abord
        for w in waypoints:
            f.write(_wpt_xml(w))

        # Un track par relais
        for relay in sorted_relays:
            s = to_active(relay["start"])
            e = to_active(relay["end"])
            ap_start = relay.get("start_acces")
            ap_end = relay.get("end_acces")

            km_start = ap_start["km_cross"] if ap_start else s * segment_km
            km_end = ap_end["km_cross"] if ap_end else e * segment_km

            sliced = _slice_points(points, km_start, km_end)
            f.write(_trk_xml(relay, sliced))

        f.write("</gpx>\n")
