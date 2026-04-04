
DEFAULT_PROFILE = "gpx/altitude.csv"


class Profile:

    def __init__(self, distances: list[float], altitudes: list[float]):
        """
        distances : liste de distances en mètres (triée, croissante)
        altitudes : liste d'altitudes correspondantes en mètres
        """
        self._distances = distances
        self._altitudes = altitudes

    def _altitude_at(self, km: float) -> float:
        """Interpolation linéaire de l'altitude au point kilométrique donné."""
        m = km * 1000.0
        d = self._distances
        a = self._altitudes

        if m <= d[0]:
            return a[0]
        if m >= d[-1]:
            return a[-1]

        # recherche binaire de l'intervalle
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
        """
        Intègre les dénivelés positifs et négatifs entre les deux points
        kilométriques indiqués.

        Retourne (d_plus, d_moins) en mètres (d_moins est positif).
        """
        # résolution : un point tous les 100 m dans le CSV → on itère directement
        # sur les points du profil compris dans l'intervalle
        m_deb = km_deb * 1000.0
        m_fin = km_fin * 1000.0

        if m_deb > m_fin:
            m_deb, m_fin = m_fin, m_deb

        d = self._distances
        a = self._altitudes

        # borne les indices dans le tableau
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

        # premier point : interpolé au km_deb
        points = [self._altitude_at(km_deb)]

        # points intermédiaires strictement dans l'intervalle
        for i in range(i_start, i_end + 1):
            if d[i] > m_deb and d[i] < m_fin:
                points.append(a[i])

        # dernier point : interpolé au km_fin
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

    def cumul_denivele(
        self, nb_active_segs: int, segment_km: float
    ) -> list[tuple[float, float]]:
        """Pré-calcule les dénivelés cumulatifs aux bornes de chaque segment actif.

        Retourne une liste de longueur nb_active_segs + 1, où l'élément i contient
        (cumul_d_plus, cumul_d_moins) depuis le km 0 jusqu'au début du segment i.

        Le D+/D- du segment actif s est alors :
            dp = cumul[s+1][0] - cumul[s][0]
            dm = cumul[s+1][1] - cumul[s][1]

        Et le D+/D- d'un relais [start, end) (indices actifs) est :
            dp = cumul[end][0] - cumul[start][0]
            dm = cumul[end][1] - cumul[start][1]
        """
        cumul: list[tuple[float, float]] = [(0.0, 0.0)]
        dp_acc, dm_acc = 0.0, 0.0
        for s in range(nb_active_segs):
            km_deb = s * segment_km
            km_fin = (s + 1) * segment_km
            dp, dm = self.denivele(km_deb, km_fin)
            dp_acc += dp
            dm_acc += dm
            cumul.append((dp_acc, dm_acc))
        return cumul

    def to_svg(
        self,
        width: int = 900,
        height: int = 300,
        padding_left: int = 50,
        padding_right: int = 20,
        padding_top: int = 20,
        padding_bottom: int = 40,
        speed_kmh: float = 9.0,
        pauses: list[tuple[float, float]] | None = None,
        inline: bool = False,
    ) -> str:
        """Renvoie le profil altimétrique sous forme d'image SVG (chaîne de caractères).

        Si speed_kmh est fourni, l'axe horizontal représente le temps de course
        (heures depuis le départ). Les pauses, si fournies, sont affichées comme
        des bandes verticales grisées et s'ajoutent au temps total.

        pauses : liste de (km_position, duree_heures) — pause insérée après le
                 km indiqué, de la durée indiquée.
        inline : si True, adapte le SVG pour une inclusion dans une page HTML —
                 width="100%", preserveAspectRatio="none", style="display:block".
        """
        import math

        d = self._distances
        a = self._altitudes

        km_min = d[0] / 1000.0
        km_max = d[-1] / 1000.0
        alt_min = min(a)
        alt_max = max(a)
        alt_range = alt_max - alt_min or 1.0

        plot_w = width - padding_left - padding_right
        plot_h = height - padding_top - padding_bottom

        # --- conversion km → temps (heures) ---
        # Durée de course pure (sans pauses) à chaque km :
        #   t_course(km) = km / speed_kmh
        # Les pauses décalent le temps pour tous les km suivants.
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
            f'<polyline points="{line_str}" fill="none" stroke="#2a5fa5" stroke-width="1.5"/>'
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


def load_profile(filename: str = DEFAULT_PROFILE) -> Profile:
    """Charge le fichier CSV et renvoie un Profile prêt à l'emploi."""
    distances = []
    altitudes = []

    with open(filename, newline="", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            parts = line.split(";")
            if len(parts) < 2:
                continue
            try:
                dist = float(parts[0])
                alt = float(parts[1])
            except ValueError:
                continue
            distances.append(dist)
            altitudes.append(alt)

    return Profile(distances, altitudes)
