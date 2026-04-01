"""
Rendu texte, CSV et HTML des solutions.

API publique :
  to_text(solution) -> str
  to_csv(solution, filename)
  to_html(solution) -> str
"""

import csv
from dataclasses import dataclass, field

DAY_NAMES = ["Mercredi", "Jeudi", "Vendredi"]
DAY_SHORT = ["Mer", "Jeu", "Ven"]

PROFIL_SVG_HEIGHT = 140
PLANNING_WIDTH = 85
GANTT_HOUR_MARKS = (0, 6, 12, 18)
GANTT_DAYS = 4


# TRI_GANTT determine l'ordre des lignes dans le gantt
# "decl" = ordre des new_runner() - constant
# "alpha" = ordre alphabétique - constant
# "start" = par ordre de départ - variable selon solutions
TRI_GANTT = "decl"

DENIV_WIDTH = 6  # signe + 4 chiffres max + 'm'


# Colonnes du CSV export (ordre fixe et noms lisibles)
CSV_FIELDS = (
    "coureur", "partenaire", "k",
    "debut_txt", "fin_txt",
    "debut_seg", "fin_seg",
    "debut_heure", "fin_heure",
    "debut_km", "fin_km", "distance_km",
    "solo", "nuit", "flex", "pinned",
    "rest_h", "d_plus", "d_moins",
)

_CSS_CLASS_MAP = {
    "free":        "seg-free",
    "rest":        "seg-rest",
    "relay_binome": "seg-binome",
    "relay_flex":  "seg-flex",
    "relay_solo":  "seg-solo",
    "relay_fixe":  "seg-fixe",
    "unavail":     "seg-unavail",
}

_TAG_CONFIG = [
    ("fixe", lambda r: r["pinned"] is not None),
    ("solo", lambda r: r["solo"]),
    ("nuit", lambda r: r["night"]),
    ("flex", lambda r: r["flex"]),
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


def _fmt_seg_short(constraints, seg):
    h = constraints.segment_start_hour(seg)
    day, hh, mm = _split_hour(h)
    return DAY_SHORT[min(day, 2)], hh, mm


def _max_label_width(relays, label_fn) -> int:
    return max((len(label_fn(r)) for r in relays), default=0)


def _build_pause_entry(constraints, time_start: int, time_end: int) -> ChronoEntry:
    c = constraints
    ph_start = c.segment_start_hour(time_start)
    ph_end = c.segment_start_hour(time_end)
    d_start, hh, mm = _split_hour(ph_start)
    d_end, hh_end, mm_end = _split_hour(ph_end)
    dur_str = _fmt_duration(ph_end - ph_start)
    active = c.time_seg_to_active(time_start)
    return ChronoEntry(
        kind="pause",
        day_s=DAY_SHORT[min(d_start, 2)], hh=hh, mm=mm,
        day_e=DAY_SHORT[min(d_end, 2)], hh_end=hh_end, mm_end=mm_end,
        seg_start=active,
        km_start=active * c.segment_km,
        dur_str=dur_str,
    )



# ------------------------------------------------------------------
# Export CSV
# ------------------------------------------------------------------


def _csv_row(rel, constraints):
    c = constraints
    h_s = c.segment_start_hour(rel["start"])
    day_s_idx, hh, mm = _split_hour(h_s)
    day_s = DAY_SHORT[min(day_s_idx, 2)]
    h_e = c.segment_start_hour(rel["end"])
    _, hh_e, mm_e = _split_hour(h_e)

    def r3(v):
        return round(v, 3) if v is not None else None

    return {
        "coureur": rel["runner"],
        "partenaire": rel["partner"],
        "debut_txt": f"{day_s} {hh:02d}h{mm:02d}",
        "fin_txt": f"{day_s} {hh_e:02d}h{mm_e:02d}",
        "debut_seg": rel["start"],
        "fin_seg": rel["end"],
        "debut_heure": r3(c.segment_start_hour(rel["start"])),
        "fin_heure": r3(c.segment_start_hour(rel["end"])),
        "debut_km": r3(c.time_seg_to_active(rel["start"]) * c.segment_km),
        "fin_km": r3(c.time_seg_to_active(rel["end"]) * c.segment_km),
        "distance_km": r3(rel["km"]),
        "k": rel["k"],
        "solo": rel["solo"],
        "nuit": rel["night"],
        "flex": rel["flex"],
        "pinned": rel.get("pinned"),
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


# ------------------------------------------------------------------
# Construction des données intermédiaires pour HTML et texte
# ------------------------------------------------------------------


def build_chrono_entries(relays, constraints) -> list:
    """Retourne la liste plate de ChronoEntry du planning chronologique."""
    c = constraints
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

        day_s, hh, mm = _fmt_seg_short(c, rel["start"])
        day_e, hh_end, mm_end = _fmt_seg_short(c, rel["end"])
        coureurs = f"{rel['runner']} + {rel['partner']}" if rel["partner"] else rel["runner"]
        entries.append(ChronoEntry(
            day_s=day_s, hh=hh, mm=mm, day_e=day_e, hh_end=hh_end, mm_end=mm_end,
            seg_start=c.time_seg_to_active(rel["start"]),
            time_seg_start=rel["start"],
            km_start=c.time_seg_to_active(rel["start"]) * c.segment_km,
            km_dist=rel["km"],
            coureurs=coureurs,
            d_plus=rel.get("d_plus"),
            d_moins=rel.get("d_moins"),
            tags=_build_tags(rel),
            rel=rel,
        ))

        for a, b in c.inactive_ranges:
            if rel["end"] == a and a not in pause_inserted:
                pause_inserted.add(a)
                entries.append(_build_pause_entry(c, a, b))

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
            day_s, hh, mm = _fmt_seg_short(c, rel["start"])
            _, hh_e, mm_e = _fmt_seg_short(c, rel["end"])
            p = f"avec {rel['partner']}" if rel["partner"] else "seul"
            rest_h = rel["rest_h"]
            if rest_h is not None:
                rh, rm = int(rest_h), int((rest_h % 1) * 60)
                repos_str = f"repos {rh:2d}h{rm:02d}"
            else:
                repos_str = ""
            relais_lines.append(RelaisLine(
                day_s=day_s, hh=hh, mm=mm, hh_e=hh_e, mm_e=mm_e,
                seg_start=c.time_seg_to_active(rel["start"]),
                km_start=c.time_seg_to_active(rel["start"]) * c.segment_km,
                km_dist=rel["km"],
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
        total_duration_h = sum(x["size"] for x in r_rels) * c.segment_duration
        recaps.append(RunnerRecap(
            name=r, total_km=total, n_relais=len(r_rels),
            n_solo=n_solo, n_nuit=n_nuit,
            total_d_plus=total_d_plus, total_d_moins=total_d_moins,
            total_duration_h=total_duration_h,
            relais=relais_lines,
        ))
    return recaps


# ------------------------------------------------------------------
# Rendu texte
# ------------------------------------------------------------------


def _summary_data(solution):
    """Données communes aux résumés texte et HTML."""
    c = solution.constraints
    score, _, n_solos, _, _, _, km_flex = solution.stats()
    min_per_km = 60.0 / c.speed_kmh
    h_start = c.start_hour
    h_end = c.segment_start_hour(c.nb_segments)
    d_start, hh_start, mm_start = _split_hour(h_start)
    d_end, hh_end, mm_end = _split_hour(h_end)
    return {
        "nb_coureurs":    len(c.runners),
        "km_engages":     sum(r["size_decl"] * c.segment_km for r in solution.relays),
        "min_per_km_str": f"{int(min_per_km)}'{int((min_per_km % 1) * 60):02d}\"",
        "seg_dur_min":    c.segment_duration * 60,
        "day_start":      DAY_SHORT[min(d_start, 2)],
        "hh_start":       hh_start,
        "mm_start":       mm_start,
        "day_end":        DAY_SHORT[min(d_end, 2)],
        "hh_end":         hh_end,
        "mm_end":         mm_end,
        "lp_bound":       c.lp_bounds.upper_bound if c.lp_bounds is not None else "?",
        "score_str":      f"{score:.0f}" if score is not None else "?",
        "km_flex_str":    f"{km_flex:.1f}" if km_flex else "0",
        "n_solos":        n_solos,
    }


def _build_text_chrono(solution):
    c = solution.constraints
    relays = solution.relays
    lines = []
    d = _summary_data(solution)

    lines.append("=" * PLANNING_WIDTH)
    lines.append(f"  Planning LYS-FES  {c.total_km:.1f} km     {d['day_start']} {d['hh_start']:02d}h{d['mm_start']:02d} -> {d['day_end']} {d['hh_end']:02d}h{d['mm_end']:02d}")
    lines.append(f"  {d['nb_coureurs']} coureurs - {d['km_engages']:.1f} km engagés - {c.nb_active_segments} segments - {d['min_per_km_str']} min/km - {d['seg_dur_min']:.0f} min/segment")
    lines.append(f"  score {d['score_str']}/{d['lp_bound']} - {d['km_flex_str']} km flex - {d['n_solos']} relais solo")
    lines.append("=" * PLANNING_WIDTH)

    cw = _max_label_width(relays, lambda r: f"{r['runner']} + {r['partner']}" if r["partner"] else r["runner"])
    for entry in build_chrono_entries(relays, c):
        if entry.kind == "relay":
            debut = f"{entry.day_s} {entry.hh:02d}h{entry.mm:02d}"
            fin = f"{entry.hh_end:02d}h{entry.mm_end:02d}"
            seg_dep = f"{entry.seg_start:>3}"
            km_dep = f"{entry.km_start:>6.1f} km"
            flags = f"  [{' '.join(entry.tags)}]" if entry.tags else ""
            if entry.d_plus is not None:
                dp = f"↑{entry.d_plus:.0f}m".rjust(DENIV_WIDTH + 1)
                dm = f"↓{entry.d_moins:.0f}m".rjust(DENIV_WIDTH)
                dplus_str = f" {dp} {dm}"
            else:
                dplus_str = " " * (DENIV_WIDTH * 2 + 3)
            lines.append(f"  {debut} → {fin}   {seg_dep}   {km_dep}   {entry.km_dist:>4.1f} km   {entry.coureurs:<{cw}}{dplus_str}{flags}")
        else:
            debut_p = f"{entry.day_s} {entry.hh:02d}h{entry.mm:02d}"
            fin_p = f"{entry.hh_end:02d}h{entry.mm_end:02d}"
            seg_dep = f"{entry.seg_start:>3}"
            km_dep = f"{entry.km_start:>6.1f} km"
            pause_label = f"⏸  PAUSE {entry.dur_str}"
            lines.append(f"  {debut_p} → {fin_p}   {seg_dep}   {km_dep}   {'':>7}   {pause_label:<{cw}}")

    return lines


def _build_text_recap(solution):
    lines = []
    lines.append(f"\n{'─' * PLANNING_WIDTH}")
    lines.append("  PAR COUREUR")
    lines.append(f"{'─' * PLANNING_WIDTH}")
    pw = _max_label_width(solution.relays, lambda r: f"avec {r['partner']}" if r["partner"] else "seul")
    for recap in build_runner_recaps(solution.relays, solution.constraints):
        flags = []
        if recap.n_solo:
            flags.append(f"{recap.n_solo} seul")
        if recap.n_nuit:
            flags.append(f"{recap.n_nuit} nuit")
        if recap.total_d_plus is not None:
            dplus_total = f" {_fmt_deniv(recap.total_d_plus, '+').rjust(DENIV_WIDTH + 1)} {_fmt_deniv(recap.total_d_moins, '-').rjust(DENIV_WIDTH)}"
        else:
            dplus_total = " " * (DENIV_WIDTH * 2 + 3)
        # Aligne total_km sur la colonne km_dist : 2(indent)+18(heure)+3+3(seg)+3+9(km_dep) = 38 chars avant "   km_dist"
        RECAP_TITLE_WIDTH = 2 + 18 + 3 + 3 + 3 + 9 - 1  # = 37
        flags_str = f"  ({', '.join(flags)})" if flags else ""
        lines.append(
            f"\n{recap.name:<{RECAP_TITLE_WIDTH}}   {recap.total_km:>4.1f} km"
            f"   {'':>{pw}}{dplus_total}{flags_str}"
        )
        for rl in recap.relais:
            flags_rel = f"  [{' '.join(rl.tags)}]" if rl.tags else ""
            if rl.d_plus is not None:
                dplus_str = f" {_fmt_deniv(rl.d_plus, '+').rjust(DENIV_WIDTH + 1)} {_fmt_deniv(rl.d_moins, '-').rjust(DENIV_WIDTH)}"
            else:
                dplus_str = " " * (DENIV_WIDTH * 2 + 3)
            lines.append(
                f"  {rl.day_s} {rl.hh:02d}h{rl.mm:02d} → {rl.hh_e:02d}h{rl.mm_e:02d}"
                f"   {rl.seg_start:>3}   {rl.km_start:>6.1f} km   {rl.km_dist:>4.1f} km"
                f"   {rl.partenaire:<{pw}}{dplus_str}  {rl.repos_str:<11}{flags_rel}"
            )

    return lines


def to_text(solution) -> str:
    """Retourne le planning complet en texte (planning chrono + récap)."""
    lines = _build_text_chrono(solution) + _build_text_recap(solution)
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------
# Rendu HTML
# ------------------------------------------------------------------


def _split_spans(spans, mark_segs):
    """Divise les spans aux points de repère (ticks horaires)."""
    result = []
    for s, e, typ, label in spans:
        cuts = sorted(m for m in mark_segs if s < m < e)
        boundaries = [s] + cuts + [e]
        for i in range(len(boundaries) - 1):
            result.append((boundaries[i], boundaries[i + 1], typ, label if i == 0 else ""))
    return result


def _gantt_mark_segs(c) -> set:
    """Calcule les segments correspondant aux ticks horaires (0h, 6h, 12h, 18h)."""
    mark_segs = set()
    for day in range(GANTT_DAYS):
        for hh_mark in GANTT_HOUR_MARKS:
            target_h = day * 24 + hh_mark
            best = min(range(c.nb_segments + 1), key=lambda s: abs(c.segment_start_hour(s) - target_h))
            if 0 < best <= c.nb_segments:
                mark_segs.add(best)
    return mark_segs


def _gantt_header_row(c, mark_segs: set) -> str:
    """Retourne les deux lignes d'en-tête du Gantt (ticks horaires + barre nuit/pause)."""
    inactive_range_starts = {a: b for a, b in c.inactive_ranges}
    night_segs = c.night_segments
    sorted_marks = sorted(mark_segs)

    # row1 : ticks horaires (blocs fusionnés entre ticks)
    row1 = ['<div class="th-seg-label"></div>']
    seg = 0
    first_block = True
    while seg < c.nb_segments:
        block_end = next((m for m in sorted_marks if m > seg), c.nb_segments)
        span = block_end - seg
        h = c.segment_start_hour(seg)
        h_mod = h % 24
        closest_hh = min(GANTT_HOUR_MARKS, key=lambda hm: min(abs(h_mod - hm), 24 - abs(h_mod - hm)))
        label = "" if first_block and abs(h_mod - closest_hh) * 60 > c.segment_duration * 60 else f"{closest_hh:02d}h"
        first_block = False
        row1.append(f'<div style="grid-column:span {span}" class="th-tick-block">{label}</div>')
        seg = block_end

    # row2 : segment par segment, fond nuit ou pause
    row2 = ['<div class="th-seg-label"></div>']
    seg = 0
    while seg < c.nb_segments:
        if seg in inactive_range_starts:
            b = inactive_range_starts[seg]
            row2.append(f'<div style="grid-column:span {b - seg}" class="th-seg-px th-pause-px"></div>')
            seg = b
        else:
            night_class = " th-seg-night" if seg in night_segs else ""
            row2.append(f'<div class="th-seg-px{night_class}"></div>')
            seg += 1

    return "".join(row1) + "".join(row2)


def _gantt_runner_rows(c, relays, mark_segs: set) -> list[str]:
    """Retourne une liste de div HTML, une par coureur."""
    by_runner = {r: {} for r in c.runners}
    for rel in relays:
        by_runner[rel["runner"]][rel["start"]] = rel

    def unavail_segs(runner):
        specs = c.runners_data[runner].relais
        if any(spec.window is None for spec in specs):
            return set()
        windows = [w for spec in specs for w in spec.window]
        avail = set()
        for s, e in windows:
            avail.update(range(s, e + 1))
        return set(range(c.nb_segments)) - avail

    def first_relay_start(runner):
        rels = by_runner[runner]
        return min(rels.keys()) if rels else float("inf")

    if TRI_GANTT == "alpha":
        runner_order = sorted(c.runners)
    elif TRI_GANTT == "start":
        runner_order = sorted(c.runners, key=first_relay_start)
    else:  # "decl"
        runner_order = c.runners

    rows_html = []
    for r in runner_order:
        unavail = unavail_segs(r)
        relais_by_start = by_runner[r]
        sorted_relais = sorted(relais_by_start.values(), key=lambda x: x["start"])

        spans = []
        seg = 0
        last_repos_end = None
        while seg < c.nb_segments:
            if seg in relais_by_start:
                rel = relais_by_start[seg]
                if rel["pinned"] is not None:
                    relay_typ = "relay_fixe"
                elif rel["partner"] and rel["flex"]:
                    relay_typ = "relay_flex"
                elif rel["partner"]:
                    relay_typ = "relay_binome"
                else:
                    relay_typ = "relay_solo"
                spans.append((seg, rel["end"], relay_typ, ""))
                last_repos_end = min(rel["end"] + rel["rest_min_segs"], c.nb_segments)
                seg = rel["end"]
            elif seg in unavail:
                end = seg + 1
                while end < c.nb_segments and end in unavail and end not in relais_by_start:
                    end += 1
                spans.append((seg, end, "unavail", ""))
                seg = end
            else:
                next_event = c.nb_segments
                for rs in sorted_relais:
                    if rs["start"] > seg:
                        next_event = min(next_event, rs["start"])
                        break
                for us in sorted(unavail):
                    if us > seg:
                        next_event = min(next_event, us)
                        break
                end = next_event
                if last_repos_end is not None and seg < last_repos_end:
                    repos_end = min(last_repos_end, end)
                    spans.append((seg, repos_end, "rest", ""))
                    if repos_end < end:
                        spans.append((repos_end, end, "free", ""))
                else:
                    spans.append((seg, end, "free", ""))
                seg = end

        cells = []
        for s, e, typ, label in _split_spans(spans, mark_segs):
            colspan = e - s
            if colspan == 0:
                continue
            mark_class = " seg-mark" if s in mark_segs else ""
            cells.append(f'<div style="grid-column:span {colspan}" class="{_CSS_CLASS_MAP.get(typ, "seg-free")}{mark_class}">{label}</div>')

        rows_html.append(f'<div class="th-runner">{r}</div>' + "".join(cells))

    return rows_html


def _build_gantt(solution) -> str:
    """Retourne le div gantt-container complet (profil SVG + header + coureurs)."""
    c = solution.constraints
    mark_segs = _gantt_mark_segs(c)
    header_row = _gantt_header_row(c, mark_segs)
    rows_html = _gantt_runner_rows(c, solution.relays, mark_segs)
    inner = _build_profil_svg_row(solution) + header_row + "".join(rows_html)
    return f'<div class="gantt-container">\n{inner}\n</div>'


def _row_class(rel):
    if rel["pinned"] is not None:
        return ' class="row-fixe"'
    if rel["solo"]:
        return ' class="row-solo"'
    if rel["partner"]:
        return ' class="row-binome"'
    return ""


def _build_html_chrono(solution) -> str:
    chrono_rows = []
    for entry in build_chrono_entries(solution.relays, solution.constraints):
        if entry.kind == "relay":
            e = entry
            flags = ", ".join(e.tags)
            chrono_rows.append(
                f'<tr{_row_class(e.rel)}>'
                f'<td class="td-time td-nowrap">{e.day_s} {e.hh:02d}h{e.mm:02d} → {e.hh_end:02d}h{e.mm_end:02d}</td>'
                f'<td class="td-time td-right">{e.seg_start}</td>'
                f'<td class="td-time td-right">{e.km_start:.1f} km</td>'
                f'<td class="td-time td-right">{e.km_dist:.1f} km</td>'
                f'<td class="td-time td-right">{_fmt_deniv(e.d_plus, "+")}</td>'
                f'<td class="td-time td-right">{_fmt_deniv(e.d_moins, "-")}</td>'
                f'<td class="td-time td-bold">{e.coureurs}</td>'
                f'<td class="td-time td-meta">{flags}</td>'
                f'</tr>'
            )
        else:
            chrono_rows.append(
                f'<tr class="row-pause">'
                f'<td class="td-pause td-nowrap">{entry.day_s} {entry.hh:02d}h{entry.mm:02d} → {entry.day_e} {entry.hh_end:02d}h{entry.mm_end:02d}</td>'
                f'<td class="td-pause td-right">{entry.seg_start}</td>'
                f'<td class="td-pause td-right">{entry.km_start:.1f} km</td>'
                f'<td class="td-pause" colspan="5">⏸&nbsp; PAUSE {entry.dur_str}</td>'
                f'</tr>'
            )

    return (
        '<h3 class="section-title">Planning chronologique</h3>'
        '<table class="detail-table">'
        '<thead><tr class="thead-row">'
        '<th class="th-detail">Horaire</th>'
        '<th class="th-detail th-right">Seg.</th>'
        '<th class="th-detail th-right">Km</th>'
        '<th class="th-detail th-right">Dist.</th>'
        '<th class="th-detail th-right">D+</th>'
        '<th class="th-detail th-right">D-</th>'
        '<th class="th-detail">Coureur(s)</th>'
        '<th class="th-detail">Tags</th>'
        '</tr></thead>'
        '<tbody>' + "\n".join(chrono_rows) + '</tbody>'
        '</table>'
    )


def _build_html_recap(solution) -> str:
    recap_sections = []
    for recap in build_runner_recaps(solution.relays, solution.constraints):
        flags = []
        if recap.n_solo:
            flags.append(f"{recap.n_solo} seul")
        if recap.n_nuit:
            flags.append(f"{recap.n_nuit} nuit")
        flags_str = f" &nbsp;({', '.join(flags)})" if flags else ""

        detail_rows = []
        for rl in recap.relais:
            tags_str = ", ".join(rl.tags)
            detail_rows.append(
                f'<tr{_row_class(rl.rel)}>'
                f'<td class="td-recap td-nowrap">{rl.day_s} {rl.hh:02d}h{rl.mm:02d} → {rl.hh_e:02d}h{rl.mm_e:02d}</td>'
                f'<td class="td-recap td-right">{rl.seg_start}</td>'
                f'<td class="td-recap td-right">{rl.km_start:.1f} km</td>'
                f'<td class="td-recap td-right">{rl.km_dist:.1f} km</td>'
                f'<td class="td-recap">{rl.partenaire}</td>'
                f'<td class="td-recap td-right">{_fmt_deniv(rl.d_plus, "+")}</td>'
                f'<td class="td-recap td-right">{_fmt_deniv(rl.d_moins, "-")}</td>'
                f'<td class="td-recap td-meta">{rl.repos_str}</td>'
                f'<td class="td-recap td-meta">{tags_str}</td>'
                f'</tr>'
            )

        dur_str = _fmt_duration(recap.total_duration_h)
        summary_row = (
            f'<tr class="row-summary">'
            f'<td class="td-recap td-summary td-nowrap">{recap.n_relais} relais &nbsp; {dur_str}</td>'
            f'<td class="td-recap td-summary" colspan="2"></td>'
            f'<td class="td-recap td-summary td-right">{recap.total_km:.1f} km</td>'
            f'<td class="td-recap td-summary"></td>'
            f'<td class="td-recap td-summary td-right">{_fmt_deniv(recap.total_d_plus, "+")}</td>'
            f'<td class="td-recap td-summary td-right">{_fmt_deniv(recap.total_d_moins, "-")}</td>'
            f'<td class="td-recap td-summary td-meta"></td>'
            f'<td class="td-recap td-summary td-meta">{flags_str.strip()}</td>'
            f'</tr>'
        )
        recap_sections.append(
            f'<h4 class="runner-title">{recap.name}</h4>'
            '<table class="detail-table">'
            '<tbody>' + summary_row + "\n" + "\n".join(detail_rows) + '</tbody>'
            '</table>'
        )
    return (
        '<h3 class="section-title">Par coureur</h3>'
        + "\n".join(recap_sections)
    )


def _build_profil_svg_row(solution) -> str:
    """Retourne la ligne SVG du profil altimétrique pour le Gantt, ou '' si absent."""
    c = solution.constraints
    if c.profil is None:
        return ""
    pauses = [
        (c.time_seg_to_active(a) * c.segment_km, (b - a) * c.segment_duration)
        for a, b in c.inactive_ranges
    ]
    svg = c.profil.to_svg(
        width=900,
        height=PROFIL_SVG_HEIGHT,
        padding_left=0,
        padding_right=0,
        padding_top=10,
        padding_bottom=30,
        speed_kmh=c.speed_kmh,
        pauses=pauses if pauses else None,
        inline=True,
    )
    return (
        f'<div class="th-seg-label" style="vertical-align:bottom;font-size:10px;color:#555;"></div>'
        f'<div style="grid-column:span {c.nb_segments};padding:0;">{svg}</div>'
    )


def to_html(solution) -> str:
    """Retourne le planning complet en HTML (Gantt + planning détaillé)."""
    c = solution.constraints
    d = _summary_data(solution)

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Planning {c.total_km} km</title>
<style>
  body {{ font-family: sans-serif; font-size: 12px; margin: 16px; }}
  table {{ border-collapse: collapse; table-layout: fixed; }}
  th, td {{ padding: 2px; }}

  /* Gantt CSS Grid */
  .gantt-container {{
    overflow-x: auto;
    display: grid;
    grid-template-columns: max-content repeat({c.nb_segments}, 1fr);
  }}
  .gantt-container > div {{ box-sizing: border-box; }}

  /* Gantt — header */
  .th-seg-label {{ padding: 2px 6px; white-space: nowrap; font-size: 12px; }}
  .th-tick-block {{ font-size: 9px; padding: 1px 3px; text-align: left; white-space: nowrap; overflow: hidden; border-left: 1px solid #bbb; }}
  .th-pause-block {{ background: #ffe0b2; color: #bf360c; border-left: 1px solid #e65100; }}
  .th-seg-px {{ height: 6px; }}
  .th-seg-night {{ background: #1565c0; }}
  .th-pause-px {{ background: #ff9800; }}
  .th-runner {{ text-align: left; padding: 2px 6px; white-space: nowrap; font-size: 12px; }}

  /* Gantt — cellules segments */
  .seg-free    {{ color: #555; font-size: 10px; text-align: center; background: #ffffff;
                  border-top: 1px solid #ccc; border-bottom: 1px solid #ccc; border-left: 1px solid #ccc; border-right: 1px solid #ccc; }}
  .seg-rest    {{ color: #555; font-size: 10px; text-align: center; background: #fff9e6;
                  border-top: 1px solid #ccc; border-bottom: 1px solid #ccc; border-left: 1px solid #f9a825; border-right: 1px solid #f9a825; }}
  .seg-binome  {{ background: #43a047; color: #000; font-size: 10px; text-align: center; font-weight: bold;
                  border-top: 1px solid #ccc; border-bottom: 1px solid #ccc; border-left: 1px solid #2e7d32; border-right: 1px solid #2e7d32; }}
  .seg-flex    {{ background: #a5d6a7; color: #000; font-size: 10px; text-align: center; font-weight: bold;
                  border-top: 1px solid #ccc; border-bottom: 1px solid #ccc; border-left: 1px solid #558b2f; border-right: 1px solid #558b2f; }}
  .seg-solo    {{ background: #ef9a9a; color: #000; font-size: 10px; text-align: center; font-weight: bold;
                  border-top: 1px solid #ccc; border-bottom: 1px solid #ccc; border-left: 1px solid #b71c1c; border-right: 1px solid #b71c1c; }}
  .seg-fixe    {{ background: #7986cb; color: #fff; font-size: 10px; text-align: center; font-weight: bold;
                  border-top: 1px solid #ccc; border-bottom: 1px solid #ccc; border-left: 1px solid #283593; border-right: 1px solid #283593; }}
  .seg-unavail {{ background: #b0bec5;
                  border-top: 1px solid #ccc; border-bottom: 1px solid #ccc; border-left: 1px solid #546e7a; border-right: 1px solid #546e7a; }}
  .seg-mark    {{ border-left: 2px solid #000; }}
  .seg-pause   {{ background: #ff9800; border: 1px solid #e65100; }}

  /* Tables de détail */
  .detail-table {{ border-collapse: collapse; font-size: 12px; table-layout: auto; }}
  .section-title {{ margin-top: 2em; }}
  .thead-row {{ background: #eee; font-weight: bold; }}
  .th-detail {{ padding: 4px 8px; text-align: left; }}
  .th-detail.th-right {{ text-align: right; }}
  .runner-title {{ margin: 1.2em 0 0.3em; }}
  .runner-subtitle {{ font-weight: normal; font-size: 12px; }}

  /* Lignes colorées */
  .row-solo   {{ background: #fdf3f3; }}
  .row-binome {{ background: #f1f8f1; }}
  .row-fixe   {{ background: #f0f1fa; }}
  .row-pause  {{ background: #fff3e0; }}
  .td-pause   {{ color: #e65100; font-weight: bold; padding: 4px 8px; }}

  /* Cellules de détail */
  .td-time   {{ padding: 3px 8px; }}
  .td-recap  {{ padding: 2px 8px; }}
  .td-nowrap {{ white-space: nowrap; }}
  .td-right  {{ text-align: right; }}
  .td-bold   {{ font-weight: bold; }}
  .td-meta   {{ color: #888; font-size: 11px; }}
</style>
</head>
<body>
<h2>Planning LYS-FES &nbsp; {c.total_km:.1f} km &nbsp;|&nbsp; {d['day_start']} {d['hh_start']:02d}h{d['mm_start']:02d} → {d['day_end']} {d['hh_end']:02d}h{d['mm_end']:02d}</h2>
<p>{d['nb_coureurs']} coureurs &nbsp;|&nbsp; {d['km_engages']:.1f} km engagés &nbsp;|&nbsp; {c.nb_active_segments} segments &nbsp;|&nbsp; {d['min_per_km_str']} min/km &nbsp;|&nbsp; {d['seg_dur_min']:.0f} min/segment</p>
<p>Score <strong>{d['score_str']}</strong> (borne sup. {d['lp_bound']}) &nbsp;|&nbsp; flex <strong>{d['km_flex_str']} km</strong> &nbsp;|&nbsp; solos <strong>{d['n_solos']}</strong></p>
<p>
  <span style="background:#43a047;padding:2px 8px;border:1px solid #2e7d32;">Duo</span>&nbsp;
  <span style="background:#a5d6a7;padding:2px 8px;border:1px solid #558b2f;">Duo flex</span>&nbsp;
  <span style="background:#ef9a9a;padding:2px 8px;border:1px solid #b71c1c;">Solo</span>&nbsp;
  <span style="background:#7986cb;padding:2px 8px;border:1px solid #283593;color:#fff;">Épinglé</span>&nbsp;
  <span style="background:#b0bec5;padding:2px 8px;border:1px solid #546e7a;">Indisponible</span>&nbsp;
  <span style="background:#fff9e6;padding:2px 8px;border:1px solid #f9a825;">Repos</span>
</p>
{_build_gantt(solution)}
{_build_html_chrono(solution)}
{_build_html_recap(solution)}
</body>
</html>"""
