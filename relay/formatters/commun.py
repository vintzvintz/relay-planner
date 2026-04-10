
# TODO : add module docstring



import csv
from dataclasses import dataclass, field

#DAY_NAMES = ["Mercredi", "Jeudi", "Vendredi"]
DAY_SHORT = ["Mer", "Jeu", "Ven"]

# Colonnes du CSV export (ordre fixe et noms lisibles)
CSV_FIELDS = (
    "coureur", "partenaire", "k",
    "debut_txt", "fin_txt",
    "debut_seg", "fin_seg",
    "debut_heure", "fin_heure",
    "debut_km", "fin_km", "distance_km",
    "solo", "nuit", "pinned",
    "rest_h", "d_plus", "d_moins",
)


_TAG_CONFIG = [
    ("fixe", lambda r: r["pinned"]),
    ("solo", lambda r: r["solo"]),
    ("nuit", lambda r: r["night"]),
]


# ------------------------------------------------------------------
# Structures de données intermédiaires communes au HTML et au texte
# ------------------------------------------------------------------


@dataclass
class ChronoEntry:
    """Une ligne dans le planning chronologique (relais ou pause)."""
    kind: str = "relay"         # "relay" ou "pause"
    day_s: str = ""
    hh: int = 0
    mm: int = 0
    day_e: str = ""
    hh_end: int = 0
    mm_end: int = 0
    # Champs relais (vides pour les pauses)
    seg_start: int = 0
    time_seg_start: int = 0
    km_start: float = 0.0
    km_dist: float = 0.0
    coureurs: str = ""
    d_plus: float | None = None
    d_moins: float | None = None
    tags: list = field(default_factory=list)
    rel: dict = field(default_factory=dict)
    # Champ pause
    dur_str: str = ""


@dataclass
class RelaisLine:
    """Une ligne de relais dans le récap par coureur."""
    day_s: str = ""
    hh: int = 0
    mm: int = 0
    hh_e: int = 0
    mm_e: int = 0
    seg_start: int = 0
    km_start: float = 0.0
    km_dist: float = 0.0
    flex_str: str = ""
    d_plus: float | None = None
    d_moins: float | None = None
    partenaire: str = ""
    repos_str: str = ""
    tags: list = field(default_factory=list)
    rel: dict = field(default_factory=dict)


@dataclass
class RunnerRecap:
    """Le récap complet d'un coureur."""
    name: str = ""
    total_km: float = 0.0
    n_relais: int = 0
    n_solo: int = 0
    n_nuit: int = 0
    total_flex: float = 0.0
    total_d_plus: float | None = None
    total_d_moins: float | None = None
    total_duration_h: float = 0.0
    relais: list = field(default_factory=list)  # list[RelaisLine]



# ------------------------------------------------------------------
# Helpers bas niveau
# ------------------------------------------------------------------


def _split_hour(h: float) -> tuple[int, int, int]:
    """Convertit des heures décimales en (jour, hh, mm)."""
    day = int(h // 24)
    hh = int(h) % 24
    mm = int((h % 1) * 60)
    return day, hh, mm


def _fmt_duration(hours: float) -> str:
    """Formate une durée en heures décimales (ex: 1.5 -> '1h30')."""
    h = int(hours)
    m = int((hours % 1) * 60)
    return f"{h}h{m:02d}" if h else f"{m}min"


def _build_tags(rel) -> list[str]:
    return [name for name, condition in _TAG_CONFIG if condition(rel)]


def _fmt_deniv(value: float | None, sign: str, width: int = 0) -> str:
    if value is None:
        return ""
    s = f"{sign}{value:.0f}m"
    return s.ljust(width) if width else s


def _fmt_point_short(constraints, point):
    h = constraints._point_hour(point)
    day, hh, mm = _split_hour(h)
    return DAY_SHORT[min(day, 2)], hh, mm


def _seg_link_html(seg: int, rel: dict) -> str:
    """Retourne un lien Google Maps satellite si lat/lon connues, sinon le numéro seul."""
    lat, lon = rel.get("lat_start"), rel.get("lon_start")
    if lat is None or lon is None:
        return str(seg)
    url = f"https://www.google.com/maps?q={lat},{lon}(Seg+{seg})&t=h&z=16"
    return f'<a href="{url}" target="_blank">{seg}</a>'


def _build_pause_entry(constraints, after_point: int, wp_after_point: int, duree_heures: float) -> ChronoEntry:
    c = constraints
    ph_start = c._point_hour(after_point)
    ph_end = ph_start + duree_heures
    d_start, hh, mm = _split_hour(ph_start)
    d_end, hh_end, mm_end = _split_hour(ph_end)
    dur_str = _fmt_duration(duree_heures)
    km = c.waypoints_km[after_point]
    return ChronoEntry(
        kind="pause",
        day_s=DAY_SHORT[min(d_start, 2)], hh=hh, mm=mm,
        day_e=DAY_SHORT[min(d_end, 2)], hh_end=hh_end, mm_end=mm_end,
        seg_start=wp_after_point,
        km_start=km,
        dur_str=dur_str,
    )

# ------------------------------------------------------------------
# Construction des données intermédiaires pour HTML et texte
# ------------------------------------------------------------------


def _internal_to_user_map(constraints) -> dict[int, int]:
    """Construit le mapping index interne → index utilisateur (sans points fictifs de pause)."""
    pause_point_indices = {arc + 1 for arc in constraints.pause_arcs}
    mapping: dict[int, int] = {}
    user_idx = 0
    for i in range(constraints.nb_points):
        if i not in pause_point_indices:
            mapping[i] = user_idx
            user_idx += 1
    return mapping


def summary_data(solution):
    """Données communes aux résumés texte et HTML."""
    c = solution.constraints
    s = solution.stats()
    min_per_km = 60.0 / c.speed_kmh
    h_start = c.start_hour
    h_end = c._point_hour(c.nb_points - 1)
    d_start, hh_start, mm_start = _split_hour(h_start)
    d_end, hh_end, mm_end = _split_hour(h_end)
    return {
        "nb_coureurs":    len(c.runners),
        "km_engages":     sum(r["km"] for r in solution.relays),
        "min_per_km_str": f"{int(min_per_km)}'{int((min_per_km % 1) * 60):02d}\"",
        "nb_points":      c.nb_points,
        "day_start":      DAY_SHORT[min(d_start, 2)],
        "hh_start":       hh_start,
        "mm_start":       mm_start,
        "day_end":        DAY_SHORT[min(d_end, 2)],
        "hh_end":         hh_end,
        "mm_end":         mm_end,
        "score_str":      f"{s.score_duos:.0f}",
        "n_solos":        s.nb_solo,
        "km_solo":        s.km_solo,
        "flex_plus_str":  f"{s.flex_plus:.1f}",
        "flex_moins_str": f"{s.flex_moins:.1f}",
        "ub_score_target": s.ub_score_target,
        "ub_score_max":    s.ub_score_max,
        "lb_solos":        s.lb_solos,
    }


def build_chrono_entries(relays, constraints) -> list:
    """Retourne la liste plate de ChronoEntry du planning chronologique."""
    c = constraints
    i2u = _internal_to_user_map(c)
    entries = []
    seen = set()
    pause_inserted = set()
    for rel in relays:
        dedup = (min(rel["runner"], rel["partner"] or "zzz"),
                  max(rel["runner"], rel["partner"] or "zzz"),
                  rel["start"])
        if dedup in seen and rel["partner"]:
            continue
        seen.add(dedup)

        day_s, hh, mm = _fmt_point_short(c, rel["start"])
        day_e, hh_end, mm_end = _fmt_point_short(c, rel["end"])
        coureurs = f"{rel['runner']} + {rel['partner']}" if rel["partner"] else rel["runner"]
        entries.append(ChronoEntry(
            day_s=day_s, hh=hh, mm=mm, day_e=day_e, hh_end=hh_end, mm_end=mm_end,
            seg_start=rel["wp_start"],
            time_seg_start=rel["wp_start"],
            km_start=c.waypoints_km[rel["start"]],
            km_dist= rel["km"],
            coureurs=coureurs,
            d_plus=rel.get("d_plus"),
            d_moins=rel.get("d_moins"),
            tags=_build_tags(rel),
            rel=rel,
        ))

        for after_point, duree_heures in c._pauses:
            if duree_heures > 0 and rel["end"] == after_point and after_point not in pause_inserted:
                pause_inserted.add(after_point)
                entries.append(_build_pause_entry(c, after_point, i2u[after_point], duree_heures))

    return entries


def build_runner_recaps(relays, constraints) -> list:
    """Retourne la liste de RunnerRecap, un par coureur trié."""
    c = constraints
    recaps = []
    for r in sorted(c.runners):
        r_rels = sorted(
            [x for x in relays if x["runner"] == r], key=lambda x: x["start"]
        )
        total = sum(x["km"] for x in r_rels)
        n_solo = sum(1 for x in r_rels if x["solo"])
        n_nuit = sum(1 for x in r_rels if x["night"])

        relais_lines = []
        for rel in r_rels:
            day_s, hh, mm = _fmt_point_short(c, rel["start"])
            _, hh_e, mm_e = _fmt_point_short(c, rel["end"])
            p = f"avec {rel['partner']}" if rel["partner"] else "seul"
            rest_h = rel["rest_h"]
            if rest_h is not None:
                rh, rm = int(rest_h), int((rest_h % 1) * 60)
                repos_str = f"repos {rh:2d}h{rm:02d}"
            else:
                repos_str = ""
            diff = rel["km"] - rel["target_km"]
            flex_str = f"({diff:+.1f})"
            relais_lines.append(RelaisLine(
                day_s=day_s, hh=hh, mm=mm, hh_e=hh_e, mm_e=mm_e,
                seg_start=rel["wp_start"],
                km_start=c.waypoints_km[rel["start"]],
                km_dist= rel["km"],
                flex_str=flex_str,
                d_plus=rel.get("d_plus"),
                d_moins=rel.get("d_moins"),
                partenaire=p,
                repos_str=repos_str,
                tags=_build_tags(rel),
                rel=rel,
            ))

        dp_vals = [x["d_plus"] for x in r_rels if x.get("d_plus") is not None]
        dm_vals = [x["d_moins"] for x in r_rels if x.get("d_moins") is not None]
        total_d_plus = sum(dp_vals) if dp_vals else None
        total_d_moins = sum(dm_vals) if dm_vals else None
        total_flex = sum( x["km"] - x["target_km"] for x in r_rels)
        total_duration_h = sum(x["time_end_min"] - x["time_start_min"] for x in r_rels) / 60.0
        recaps.append(RunnerRecap(
            name=r, total_km=total, n_relais=len(r_rels),
            n_solo=n_solo, n_nuit=n_nuit,
            total_flex=total_flex,
            total_d_plus=total_d_plus, total_d_moins=total_d_moins,
            total_duration_h=total_duration_h,
            relais=relais_lines,
        ))
    return recaps





# ------------------------------------------------------------------
# Export CSV
# ------------------------------------------------------------------


def _csv_row(rel, constraints):
    c = constraints
    day_s, hh, mm = _fmt_point_short(c, rel["start"])
    _, hh_e, mm_e = _fmt_point_short(c, rel["end"])

    def r3(v):
        return round(v, 3) if v is not None else None

    return {
        "coureur": rel["runner"],
        "partenaire": rel["partner"],
        "debut_txt": f"{day_s} {hh:02d}h{mm:02d}",
        "fin_txt": f"{day_s} {hh_e:02d}h{mm_e:02d}",
        "debut_seg": rel["wp_start"],
        "fin_seg": rel["wp_end"],
        "debut_heure": r3(c._point_hour(rel["start"])),
        "fin_heure": r3(c._point_hour(rel["end"])),
        #TODO: use accessors instead of direct member access
        "debut_km": r3(c.waypoints_km[rel["start"]]),
        "fin_km": r3(c.waypoints_km[rel["end"]]),
        "distance_km": r3(rel["km"]),
        "k": rel["k"],
        "solo": rel["solo"],
        "nuit": rel["night"],
        "pinned": rel["pinned"],
        "rest_h": r3(rel["rest_h"]),
        "d_plus": r3(rel.get("d_plus")),
        "d_moins": r3(rel.get("d_moins")),
    }


def to_csv(solution, filename):
    """Sauvegarde la solution en CSV (format lisible)."""
    rows = [_csv_row(rel, solution.constraints) for rel in solution.relays]
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
