"""
relay/parcours.py — Classe Parcours : données géographiques du parcours.

Parse les waypoints (<wpt>) et le profil altimétrique (<trkpt>) depuis un
fichier GPX unique. Expose le dénivelé et le rendu SVG du profil.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

STEP_M = 100
GPX_NS = "http://www.topografix.com/GPX/1/1"

# Waypoints dont le <name> correspond à ce pattern sont ignorés lors de l'extraction
_WPT_IGNORE_RE = re.compile(r"^\d+0 km$")


class Parcours:
    """Données géographiques du parcours : waypoints + profil altimétrique.

    Instancier via le classmethod ``load_from_gpx()`` ou ``from_raw()``.
    """

    def __init__(
        self,
        waypoints: list[dict],
        profile_distances: list[float],
        profile_altitudes: list[float],
        gpx_path: str | None = None,
    ):
        """Constructeur interne.

        waypoints          : liste de dicts {km, lat, lon, alt?, name?}
        profile_distances  : distances en mètres (triée, croissante)
        profile_altitudes  : altitudes correspondantes en mètres
        gpx_path           : chemin du fichier GPX source (pour export GPX/KML)
        """
        self._waypoints = waypoints
        self._distances = profile_distances
        self._altitudes = profile_altitudes
        self.gpx_path = gpx_path

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def from_raw(
        cls,
        waypoints: list[dict],
        profile_data: list[list] | None = None,
        gpx_path: str | None = None,
    ) -> "Parcours":
        """Construit un Parcours depuis des données brutes (désérialisation, tests).

        waypoints    : liste de dicts {km, lat, lon, ...}
        profile_data : liste de [distance_m, altitude_m] (peut être None)
        gpx_path     : chemin du fichier GPX source (optionnel)
        """
        if profile_data is not None:
            distances = [float(row[0]) for row in profile_data]
            altitudes = [float(row[1]) for row in profile_data]
        else:
            distances = []
            altitudes = []
        return cls(waypoints, distances, altitudes, gpx_path=gpx_path)

    # ------------------------------------------------------------------
    # Propriétés publiques
    # ------------------------------------------------------------------

    @property
    def waypoints(self) -> list[dict]:
        """Liste des waypoints {km, lat, lon, alt?, name?}."""
        return self._waypoints

    @property
    def has_profile(self) -> bool:
        """True si un profil altimétrique est disponible."""
        return len(self._distances) > 0

    # ------------------------------------------------------------------
    # Dénivelé
    # ------------------------------------------------------------------

    def _altitude_at(self, km: float) -> float:
        """Interpolation linéaire de l'altitude au point kilométrique donné."""
        m = km * 1000.0
        d = self._distances
        a = self._altitudes

        if m <= d[0]:
            return a[0]
        if m >= d[-1]:
            return a[-1]

        lo, hi = 0, len(d) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if d[mid] <= m:
                lo = mid
            else:
                hi = mid

        t = (m - d[lo]) / (d[hi] - d[lo])
        return a[lo] + t * (a[hi] - a[lo])

    def denivele(self, km_deb: float, km_fin: float) -> tuple[float, float]:
        """Dénivelés positif et négatif entre deux points kilométriques.

        Retourne (d_plus, d_moins) en mètres (d_moins est positif).
        """
        m_deb = km_deb * 1000.0
        m_fin = km_fin * 1000.0

        if m_deb > m_fin:
            m_deb, m_fin = m_fin, m_deb

        d = self._distances
        a = self._altitudes

        def idx_ge(val):
            lo, hi = 0, len(d) - 1
            while lo < hi:
                mid = (lo + hi) // 2
                if d[mid] < val:
                    lo = mid + 1
                else:
                    hi = mid
            return lo

        i_start = idx_ge(m_deb)
        i_end = idx_ge(m_fin)

        points = [self._altitude_at(km_deb)]
        for i in range(i_start, i_end + 1):
            if d[i] > m_deb and d[i] < m_fin:
                points.append(a[i])
        points.append(self._altitude_at(km_fin))

        d_plus = 0.0
        d_moins = 0.0
        for i in range(1, len(points)):
            diff = points[i] - points[i - 1]
            if diff > 0:
                d_plus += diff
            else:
                d_moins -= diff

        return d_plus, d_moins


    # ------------------------------------------------------------------
    # Rendu SVG du profil altimétrique
    # ------------------------------------------------------------------

    def svg_profile(
        self,
        width: int = 900,
        height: int = 300,
        padding_left: int = 50,
        padding_right: int = 20,
        padding_top: int = 20,
        padding_bottom: int = 40,
        speed_kmh: float = 9.0,
        pauses: list[tuple[float, float]] | None = None,
        used_waypoint_indices: list[int] | None = None,
        inline: bool = False,
    ) -> str:
        """Renvoie le profil altimétrique sous forme d'image SVG.

        Si speed_kmh est fourni, l'axe horizontal représente le temps de course
        (heures depuis le départ). Les pauses, si fournies, sont affichées comme
        des bandes verticales grisées et s'ajoutent au temps total.

        pauses                : liste de (km_position, duree_heures)
        used_waypoint_indices : indices dans self._waypoints (numérotation sans
                                points de pause) des waypoints effectivement
                                utilisés comme points de relais — affichés en
                                rouge ; tous les autres waypoints sont affichés
                                en noir.
        inline                : si True, adapte le SVG pour une inclusion dans
                                une page HTML.
        """
        d = self._distances
        a = self._altitudes

        km_min = d[0] / 1000.0
        km_max = d[-1] / 1000.0
        alt_min = min(a)
        alt_max = max(a)
        alt_range = alt_max - alt_min or 1.0

        plot_w = width - padding_left - padding_right
        plot_h = height - padding_top - padding_bottom

        sorted_pauses = sorted(pauses or [], key=lambda p: p[0])

        def km_to_time(km: float) -> float:
            t = km / speed_kmh
            for p_km, p_dur in sorted_pauses:
                if km > p_km:
                    t += p_dur
            return t

        t_min = km_to_time(km_min)
        t_max = km_to_time(km_max)
        t_range = t_max - t_min or 1.0

        def x_of_t(t: float) -> float:
            return padding_left + (t - t_min) / t_range * plot_w

        def x_of(km: float) -> float:
            return x_of_t(km_to_time(km))

        def y_of(alt: float) -> float:
            return padding_top + (1.0 - (alt - alt_min) / alt_range) * plot_h

        # --- polygone de remplissage ---
        poly_pts = [(x_of(d[i] / 1000.0), y_of(a[i])) for i in range(len(d))]
        base_y = padding_top + plot_h
        fill_pts = (
            [(padding_left, base_y)]
            + poly_pts
            + [(padding_left + plot_w, base_y)]
        )
        fill_str = " ".join(f"{x:.1f},{y:.1f}" for x, y in fill_pts)

        # --- polyligne du profil ---
        line_str = " ".join(f"{x:.1f},{y:.1f}" for x, y in poly_pts)

        # --- graduations axe X en heures (toutes les 6h) ---
        x_tick_step = 6.0
        x_ticks_t = []
        tick_t = math.ceil(t_min / x_tick_step) * x_tick_step
        while tick_t <= t_max + 0.01:
            x_ticks_t.append(tick_t)
            tick_t += x_tick_step

        # --- graduations axe Y (tous les 100 m, arrondis) ---
        y_step = 100
        y_start = int(math.floor(alt_min / y_step)) * y_step
        y_ticks = []
        v = y_start
        while v <= alt_max + y_step:
            if v >= alt_min - 5:
                y_ticks.append(v)
            v += y_step

        lines_svg = []

        # fond blanc + bordure
        lines_svg.append(
            f'<rect x="{padding_left}" y="{padding_top}" '
            f'width="{plot_w}" height="{plot_h}" fill="white" stroke="#ccc" stroke-width="1"/>'
        )

        # --- bandes de pause ---
        for p_km, p_dur in sorted_pauses:
            t_pause_start = p_km / speed_kmh + sum(
                dur for pk, dur in sorted_pauses if pk < p_km
            )
            t_pause_end = t_pause_start + p_dur
            xp1 = x_of_t(t_pause_start)
            xp2 = x_of_t(t_pause_end)
            lines_svg.append(
                f'<rect x="{xp1:.1f}" y="{padding_top}" '
                f'width="{xp2 - xp1:.1f}" height="{plot_h}" '
                f'fill="#e8e8e8" fill-opacity="0.85" stroke="none"/>'
            )
            mid_xp = (xp1 + xp2) / 2
            lines_svg.append(
                f'<text x="{mid_xp:.1f}" y="{padding_top + plot_h / 2:.1f}" '
                f'text-anchor="middle" font-size="9" fill="#888" '
                f'transform="rotate(-90,{mid_xp:.1f},{padding_top + plot_h / 2:.1f})">'
                f'pause {p_dur:.0f}h</text>'
            )

        # grille horizontale
        for v in y_ticks:
            if alt_min <= v <= alt_max + y_step:
                yg = y_of(v)
                if padding_top <= yg <= padding_top + plot_h:
                    lines_svg.append(
                        f'<line x1="{padding_left}" y1="{yg:.1f}" '
                        f'x2="{padding_left + plot_w}" y2="{yg:.1f}" '
                        f'stroke="#e0e0e0" stroke-width="1"/>'
                    )

        # grille verticale
        for t in x_ticks_t:
            xg = x_of_t(t)
            lines_svg.append(
                f'<line x1="{xg:.1f}" y1="{padding_top}" '
                f'x2="{xg:.1f}" y2="{padding_top + plot_h}" '
                f'stroke="#e0e0e0" stroke-width="1"/>'
            )

        # zone remplie
        lines_svg.append(
            f'<polygon points="{fill_str}" fill="#b0c8e8" fill-opacity="0.7" stroke="none"/>'
        )

        # courbe
        lines_svg.append(
            f'<polyline points="{line_str}" fill="none" stroke="#2a5fa5" stroke-width="0.2mm"/>'
        )

        # --- waypoints : cercles sur le profil ---
        used_set = set(used_waypoint_indices or [])
        for idx, wpt in enumerate(self._waypoints):
            km = wpt["km"]
            alt = self._altitude_at(km)
            cx = x_of(km)
            cy = y_of(alt)
            color = "#cc0000" if idx in used_set else "#222222"
            r = 3 if idx in used_set else 2
            lines_svg.append(
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" '
                f'fill="{color}" stroke="none"/>'
            )

        # axe Y : labels
        for v in y_ticks:
            yg = y_of(v)
            if padding_top <= yg <= padding_top + plot_h:
                lines_svg.append(
                    f'<text x="{padding_left - 5}" y="{yg + 4:.1f}" '
                    f'text-anchor="end" font-size="10" fill="#555">{v}</text>'
                )

        inner = "\n  ".join(lines_svg)
        if inline:
            return (
                f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'width="100%" height="{height}" style="display:block" '
                f'viewBox="0 0 {width} {height}" preserveAspectRatio="none">\n  '
                f'{inner}\n</svg>\n'
            )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">\n  '
            f'{inner}\n</svg>\n'
        )

    # ------------------------------------------------------------------
    # Sérialisation
    # ------------------------------------------------------------------

    def to_raw(self) -> tuple[list[dict], list[list] | None]:
        """Retourne (waypoints, profile_data) pour sérialisation.

        profile_data : liste de [distance_m, altitude_m], ou None si pas de profil.
        """
        if not self.has_profile:
            return list(self._waypoints), None
        profile_data = [
            [self._distances[i], self._altitudes[i]]
            for i in range(len(self._distances))
        ]
        return list(self._waypoints), profile_data


# ---------------------------------------------------------------------------
# Free function — point d'entrée principal pour charger un parcours GPX
# ---------------------------------------------------------------------------


def load_gpx(gpx_path: str) -> Parcours:
    """Parse un fichier GPX et retourne un Parcours.

    Le fichier GPX doit contenir des <wpt> (waypoints / points de relais)
    et un <trk> avec des <trkpt> (tracé avec altitudes).
    """
    print(f"Chargement GPX : {gpx_path}")
    wpt_raw, track = _parse_gpx(gpx_path)
    cum_km = _build_cumulative_km(track)
    waypoints = _project_waypoints(wpt_raw, track, cum_km)
    profile = _build_altitude_profile(track)
    distances = [float(row[0]) for row in profile]
    altitudes = [float(row[1]) for row in profile]
    return Parcours(waypoints, distances, altitudes, gpx_path=gpx_path)


# ---------------------------------------------------------------------------
# Helpers internes (parsing GPX)
# ---------------------------------------------------------------------------


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance géodésique en mètres (formule haversine)."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _parse_gpx(gpx_path: str) -> tuple[list[dict], list[tuple]]:
    """Retourne (wpt_raw, track) depuis <wpt> et <trkpt> du GPX."""
    tree = ET.parse(gpx_path)
    root = tree.getroot()

    wpt_raw: list[dict] = []
    for wpt in root.findall(f"{{{GPX_NS}}}wpt"):
        lat = float(wpt.attrib["lat"])
        lon = float(wpt.attrib["lon"])
        ele_el = wpt.find(f"{{{GPX_NS}}}ele")
        ele = float(ele_el.text) if ele_el is not None and ele_el.text else None
        name_el = wpt.find(f"{{{GPX_NS}}}name")
        name = name_el.text.strip() if name_el is not None and name_el.text else ""
        if _WPT_IGNORE_RE.match(name):
            continue
        wpt_raw.append({"lat": lat, "lon": lon, "ele": ele, "name": name})

    track: list[tuple] = []
    for trkpt in root.iter(f"{{{GPX_NS}}}trkpt"):
        lat = float(trkpt.attrib["lat"])
        lon = float(trkpt.attrib["lon"])
        ele_el = trkpt.find(f"{{{GPX_NS}}}ele")
        ele = float(ele_el.text) if ele_el is not None and ele_el.text else 0.0
        track.append((lat, lon, ele))

    if not track:
        raise ValueError(f"Aucun <trkpt> trouvé dans {gpx_path}")

    return wpt_raw, track


def _build_cumulative_km(track: list[tuple]) -> list[float]:
    """Distances cumulatives en km le long du tracé (Haversine)."""
    cum = [0.0]
    for i in range(1, len(track)):
        lat1, lon1, _ = track[i - 1]
        lat2, lon2, _ = track[i]
        cum.append(cum[-1] + _haversine_m(lat1, lon1, lat2, lon2) / 1000)
    return cum


def _project_waypoints(
    wpt_raw: list[dict], track: list[tuple], cum_km: list[float]
) -> list[dict]:
    """Projette chaque wpt sur la trace → km. Trie par km croissant."""
    result: list[dict] = []
    for wpt in wpt_raw:
        lat, lon = wpt["lat"], wpt["lon"]
        best_km = 0.0
        best_dist = float("inf")

        for i in range(len(track) - 1):
            lat1, lon1, _ = track[i]
            lat2, lon2, _ = track[i + 1]

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
            dist = _haversine_m(lat, lon, proj_lat, proj_lon)

            if dist < best_dist:
                best_dist = dist
                seg_km = cum_km[i + 1] - cum_km[i]
                best_km = cum_km[i] + t * seg_km

        entry: dict = {
            "km": round(best_km, 2),
            "lat": lat,
            "lon": lon,
        }
        if wpt["ele"] is not None:
            entry["alt"] = round(wpt["ele"], 1)
        if wpt["name"]:
            entry["name"] = wpt["name"]
        result.append(entry)

    result.sort(key=lambda x: x["km"])
    return result


def _build_altitude_profile(
    track: list[tuple], step_m: int = STEP_M
) -> list[list]:
    """Rééchantillonnage à step_m. Retourne liste de [distance_m, altitude_m]."""
    raw: list[tuple[float, float]] = [(0.0, track[0][2])]
    cum = 0.0
    for i in range(1, len(track)):
        lat1, lon1, _ = track[i - 1]
        lat2, lon2, ele = track[i]
        cum += _haversine_m(lat1, lon1, lat2, lon2)
        raw.append((cum, ele))

    total = raw[-1][0]
    output: list[list] = []
    d = 0.0
    i = 0
    while d <= total + 1e-6:
        while i + 1 < len(raw) and raw[i + 1][0] < d:
            i += 1
        if i + 1 >= len(raw):
            output.append([round(d), raw[-1][1]])
            break
        d0, alt0 = raw[i]
        d1, alt1 = raw[i + 1]
        if d1 == d0:
            alt = alt0
        else:
            t = (d - d0) / (d1 - d0)
            alt = alt0 + t * (alt1 - alt0)
        output.append([round(d), round(alt, 1)])
        d += step_m

    return output
