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

# Colonnes du CSV export (ordre et noms lisibles)
CSV_FIELDS = (
    "coureur", "partenaire", "k",
    "debut_txt", "fin_txt",
    "debut_seg", "fin_seg",
    "debut_heure", "fin_heure",
    "debut_km", "fin_km", "distance_km", 
    "solo", "nuit", "flex", "pinned",
    "rest_h", "d_plus", "d_moins",
)


# ------------------------------------------------------------------
# Structures de données intermédiaires
# ------------------------------------------------------------------


@dataclass
class ChronoRelay:
    """Une ligne de relais dans le planning chronologique."""
    kind: str = "relay"
    day_s: str = ""
    hh: int = 0
    mm: int = 0
    hh_end: int = 0
    mm_end: int = 0
    seg_start: int = 0
    time_seg_start: int = 0
    km_start: float = 0.0
    km_dist: float = 0.0
    coureurs: str = ""
    d_plus: float | None = None
    d_moins: float | None = None
    tags: list = field(default_factory=list)
    rel: dict = field(default_factory=dict)


@dataclass
class ChronoPause:
    """Une ligne de pause dans le planning chronologique."""
    kind: str = "pause"
    dur_str: str = ""
    ds: str = ""
    hs: int = 0
    ms: int = 0
    de: str = ""
    he: int = 0
    me: int = 0


@dataclass
class RelaisLine:
    """Une ligne de relais dans le récap par coureur."""
    day_s: str = ""
    hh: int = 0
    mm: int = 0
    hh_e: int = 0
    mm_e: int = 0
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


def _chrono_tags(rel):
    return [t for t, v in [("fixe", (rel["pinned"] is not None)), ("solo", rel["solo"]), ("nuit", rel["night"])] if v]


def _recap_tags(rel):
    return [t for t, v in [("fixe", (rel["pinned"] is not None)), ("nuit", rel["night"]), ("flex", rel["flex"])] if v]


def _dedup_key(rel):
    return (
        min(rel["runner"], rel["partner"] or "zzz"),
        max(rel["runner"], rel["partner"] or "zzz"),
        rel["start"],
    )


def _fmt_dplus(d_plus: float | None, width: int = 0) -> str:
    if d_plus is None:
        return ""
    s = f"+{d_plus:.0f}m"
    return s.ljust(width) if width else s


def _fmt_dmoins(d_moins: float | None, width: int = 0) -> str:
    if d_moins is None:
        return ""
    s = f"-{d_moins:.0f}m"
    return s.ljust(width) if width else s


def _fmt_elevation(d_plus: float | None, d_moins: float | None,
                   wp: int = 0, wm: int = 0) -> str:
    if d_plus is None:
        return ""
    dp = f"+{d_plus:.0f}m"
    dm = f"-{d_moins:.0f}m"
    if wp:
        dp = dp.rjust(wp)
    if wm:
        dm = dm.rjust(wm)
    return f"{dp} {dm}"


def _elevation_widths(relays_iter) -> tuple[int, int]:
    """Calcule la largeur max de ↑Xm et ↓Xm sur une liste de relais."""
    wp = wm = 0
    for rel in relays_iter:
        dp = rel.get("d_plus")
        dm = rel.get("d_moins")
        if dp is not None:
            wp = max(wp, len(f"+{dp:.0f}m"))
            wm = max(wm, len(f"-{dm:.0f}m"))
    return wp, wm


# def _fmt_seg(constraints, seg):
#     h = constraints.segment_start_hour(seg)
#     day, hh, mm = int(h // 24), int(h) % 24, int((h % 1) * 60)
#     return DAY_NAMES[min(day, 2)], hh, mm


def _fmt_seg_short(constraints, seg):
    h = constraints.segment_start_hour(seg)
    day, hh, mm = int(h // 24), int(h) % 24, int((h % 1) * 60)
    return DAY_SHORT[min(day, 2)], hh, mm

# TODO remove duplicate with _fmt_seg_short
def _fmt_seg_short_end(constraints, seg):
    h = constraints.segment_start_hour(seg)
    day, hh, mm = int(h // 24), int(h) % 24, int((h % 1) * 60)
    return DAY_SHORT[min(day, 2)], hh, mm


def _chrono_coureurs_width(relays):
    seen = set()
    w = 0
    for rel in relays:
        dedup = _dedup_key(rel)
        if dedup in seen and rel["partner"]:
            continue
        seen.add(dedup)
        label = f"{rel['runner']} + {rel['partner']}" if rel["partner"] else rel["runner"]
        w = max(w, len(label))
    return w


def _recap_partenaire_width(relays):
    w = 0
    for rel in relays:
        label = f"avec {rel['partner']}" if rel["partner"] else "seul"
        w = max(w, len(label))
    return w


def _pause_info(constraints, time_start: int, time_end: int) -> ChronoPause:
    c = constraints
    ph_start = c.segment_start_hour(time_start)
    ph_end = c.segment_start_hour(time_end)
    d_start, d_end = int(ph_start // 24), int(ph_end // 24)
    hs, ms = int(ph_start) % 24, int((ph_start % 1) * 60)
    he, me = int(ph_end) % 24, int((ph_end % 1) * 60)
    ds = DAY_SHORT[min(d_start, 2)]
    de = DAY_SHORT[min(d_end, 2)]
    dur = ph_end - ph_start
    dur_h, dur_m = int(dur), int((dur % 1) * 60)
    dur_str = f"{dur_h}h{dur_m:02d}" if dur_h else f"{dur_m}min"
    return ChronoPause(dur_str=dur_str, ds=ds, hs=hs, ms=ms, de=de, he=he, me=me)


# ------------------------------------------------------------------
# Construction des données intermédiaires
# ------------------------------------------------------------------


def build_chrono_entries(relays, constraints) -> list:
    """Retourne la liste plate (ChronoRelay | ChronoPause) du planning chronologique."""
    c = constraints
    entries = []
    seen = set()
    pause_inserted = set()
    for rel in relays:
        dedup = _dedup_key(rel)
        if dedup in seen and rel["partner"]:
            continue
        seen.add(dedup)

        day_s, hh, mm = _fmt_seg_short(c, rel["start"])
        _, hh_end, mm_end = _fmt_seg_short_end(c, rel["end"])
        coureurs = f"{rel['runner']} + {rel['partner']}" if rel["partner"] else rel["runner"]
        entries.append(ChronoRelay(
            day_s=day_s, hh=hh, mm=mm, hh_end=hh_end, mm_end=mm_end,
            seg_start=c.time_seg_to_active(rel["start"]),
            time_seg_start=rel["start"],
            km_start=c.time_seg_to_active(rel["start"]) * c.segment_km,
            km_dist=rel["km"],
            coureurs=coureurs,
            d_plus=rel.get("d_plus"),
            d_moins=rel.get("d_moins"),
            tags=_chrono_tags(rel),
            rel=rel,
        ))

        for a, b in c.inactive_ranges:
            if rel["end"] == a and a not in pause_inserted:
                pause_inserted.add(a)
                entries.append(_pause_info(c, a, b))

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
                km_dist=rel["km"],
                d_plus=rel.get("d_plus"),
                d_moins=rel.get("d_moins"),
                partenaire=p,
                repos_str=repos_str,
                tags=_recap_tags(rel),
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
    return {
        "nb_coureurs":   len(c.runners),
        "km_engages":    sum(r["size_decl"] * c.segment_km for r in solution.relays),
        "min_per_km_str": f"{int(min_per_km)}'{int((min_per_km % 1) * 60):02d}\"",
        "seg_dur_min":   c.segment_duration * 60,
        "day_start":     DAY_SHORT[min(int(h_start // 24), 2)],
        "hh_start":      int(h_start) % 24,
        "mm_start":      int((h_start % 1) * 60),
        "day_end":       DAY_SHORT[min(int(h_end // 24), 2)],
        "hh_end":        int(h_end) % 24,
        "mm_end":        int((h_end % 1) * 60),
        "lp_bound":      c.lp_bounds.upper_bound if c.lp_bounds is not None else "?",
        "score_str":     f"{score:.0f}" if score is not None else "?",
        "km_flex_str":   f"{km_flex:.1f}" if km_flex else "0",
        "n_solos":       n_solos,
    }


def _planning_chrono_lines(solution):
    c = solution.constraints
    relays = solution.relays
    W = 74
    lines = []
    d = _summary_data(solution)

    lines.append("=" * W)
    lines.append(f"  Planning LYS-FES  {c.total_km:.1f} km     {d['day_start']} {d['hh_start']:02d}h{d['mm_start']:02d} -> {d['day_end']} {d['hh_end']:02d}h{d['mm_end']:02d}")
    lines.append(f"  {d['nb_coureurs']} coureurs - {d['km_engages']:.1f} km engagés - {c.nb_active_segments} segments - {d['min_per_km_str']} min/km - {d['seg_dur_min']:.0f} min/segment")
    lines.append(f"  score {d['score_str']}/{d['lp_bound']} - {d['km_flex_str']} km flex - {d['n_solos']} relais solo")
    lines.append("=" * W)

    cw = _chrono_coureurs_width(relays)
    wp, wm = _elevation_widths(relays)
    current_day = -1
    for entry in build_chrono_entries(relays, c):
        if isinstance(entry, ChronoRelay):
            day = int(c.segment_start_hour(entry.time_seg_start) // 24)
            if day != current_day:
                current_day = day
                lines.append(f"\n▶ {DAY_NAMES[min(day, 2)].upper()}")
            debut = f"{entry.day_s} {entry.hh:02d}h{entry.mm:02d}"
            fin = f"{entry.hh_end:02d}h{entry.mm_end:02d}"
            seg_dep = f"{entry.seg_start:>3}"
            km_dep = f"{entry.km_start:>6.1f} km"
            flags = f"  [{' '.join(entry.tags)}]" if entry.tags else ""
            if entry.d_plus is not None:
                dp = f"↑{entry.d_plus:.0f}m".rjust(wp + 1)
                dm = f"↓{entry.d_moins:.0f}m".rjust(wm)
                dplus_str = f" {dp} {dm}"
            else:
                dplus_str = " " * (wp + wm + 3)
            lines.append(f"  {debut} → {fin}   {seg_dep}   {km_dep}   {entry.km_dist:>4.1f} km   {entry.coureurs:<{cw}}{dplus_str}{flags}")
        else:
            p = entry
            debut_p = f"{p.ds} {p.hs:02d}h{p.ms:02d}"
            fin_p = f"{p.he:02d}h{p.me:02d}"
            lines.append(f"  {debut_p} → {fin_p}   ⏸  PAUSE {p.dur_str}")

    return lines


def _recap_coureurs_lines(solution):
    W = 74
    lines = []
    lines.append(f"\n{'─' * W}")
    lines.append("  PAR COUREUR")
    lines.append(f"{'─' * W}")
    pw = _recap_partenaire_width(solution.relays)
    wp, wm = _elevation_widths(solution.relays)
    for recap in build_runner_recaps(solution.relays, solution.constraints):
        flags = []
        if recap.n_solo:
            flags.append(f"{recap.n_solo} seul")
        if recap.n_nuit:
            flags.append(f"{recap.n_nuit} nuit")
        dplus_total = _fmt_elevation(recap.total_d_plus, recap.total_d_moins)
        if dplus_total:
            dplus_total = "  " + dplus_total
        lines.append(
            f"\n{recap.name:<12}  {recap.total_km:>5.1f} km  {recap.n_relais} relais{dplus_total}"
            + (f"  ({', '.join(flags)})" if flags else "")
        )
        for rl in recap.relais:
            flags_rel = f"  [{' '.join(rl.tags)}]" if rl.tags else ""
            if rl.d_plus is not None:
                dplus_str = " " + _fmt_elevation(rl.d_plus, rl.d_moins, wp=wp, wm=wm)
            else:
                dplus_str = " " * (wp + wm + 2)
            lines.append(
                f"  {rl.day_s} {rl.hh:02d}h{rl.mm:02d} → {rl.hh_e:02d}h{rl.mm_e:02d}"
                f"  {rl.km_dist:>4.1f} km{dplus_str}  {rl.partenaire:<{pw}}  {rl.repos_str:<11}{flags_rel}"
            )

    return lines


def to_text(solution) -> str:
    """Retourne le planning complet en texte (planning chrono + récap)."""
    lines = _planning_chrono_lines(solution) + _recap_coureurs_lines(solution)
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------
# Rendu HTML
# ------------------------------------------------------------------


def _build_gantt(solution):
    """Retourne (header_row, rows_html) pour le Gantt

    header_row : str  — un <div class="gantt-row gantt-header"> complet
    rows_html  : list[str] — un <div class="gantt-row"> par coureur
    """
    c = solution.constraints
    relays = solution.relays

    by_runner = {r: {} for r in c.runners}
    for rel in relays:
        by_runner[rel["runner"]][rel["start"]] = rel

    inactive_range_starts = {a: b for a, b in c.inactive_ranges}

    def unavail_segs(runner):
        specs = c.runners_data[runner].relais
        if any(spec.window is None for spec in specs):
            return set()
        windows = [w for spec in specs for w in spec.window]
        avail = set()
        for s, e in windows:
            avail.update(range(s, e + 1))
        return set(range(c.nb_segments)) - avail

    mark_segs = set()
    for day in range(4):
        for hh_mark in (0, 6, 12, 18):
            target_h = day * 24 + hh_mark
            best = min(range(c.nb_segments + 1), key=lambda s: abs(c.segment_start_hour(s) - target_h))
            if 0 < best <= c.nb_segments:
                mark_segs.add(best)

    def split_spans(spans):
        result = []
        for s, e, typ, label in spans:
            cuts = sorted(m for m in mark_segs if s < m < e)
            boundaries = [s] + cuts + [e]
            for i in range(len(boundaries) - 1):
                result.append((boundaries[i], boundaries[i + 1], typ, label if i == 0 else ""))
        return result

    def _typ_to_css(typ, mark_class):
        if typ == "free":
            return f"seg-free{mark_class}"
        elif typ == "rest":
            return f"seg-rest{mark_class}"
        elif typ == "relay_binome":
            return f"seg-binome{mark_class}"
        elif typ == "relay_flex":
            return f"seg-flex{mark_class}"
        elif typ == "relay_solo":
            return f"seg-solo{mark_class}"
        elif typ == "relay_fixe":
            return f"seg-fixe{mark_class}"
        elif typ == "unavail":
            return f"seg-unavail{mark_class}"
        else:
            return f"seg-free{mark_class}"

    rows_html = []
    for r in sorted(c.runners):
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
                elif rel["solo"]:
                    relay_typ = "relay_solo"
                elif rel["flex"] and rel["partner"]:
                    relay_typ = "relay_flex"
                else:
                    relay_typ = "relay_binome" if rel["partner"] else "relay_solo"
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

        spans = split_spans(spans)

        cells = []
        for s, e, typ, label in spans:
            colspan = e - s
            if colspan == 0:
                continue
            mark_class = " seg-mark" if s in mark_segs else ""
            css_class = _typ_to_css(typ, mark_class)
            cells.append(f'<div style="grid-column:span {colspan}" class="{css_class}">{label}</div>')

        rows_html.append(
            f'<div class="th-runner">{r}</div>'
            + "".join(cells)
        )

    night_segs = c.night_segments

    # Ligne 1 : blocs entre ticks 6h (cellules fusionnées), label à gauche, sans fond
    # Ligne 2 : 1 cellule par segment, sans texte, fond nuit ou pause
    row1 = ['<div class="th-seg-label"></div>']
    row2 = ['<div class="th-seg-label"></div>']

    sorted_marks = sorted(mark_segs)

    # row1 : ticks horaires uniquement, les pauses sont transparentes (span continu)
    seg = 0
    first_block = True
    while seg < c.nb_segments:
        block_end = next((m for m in sorted_marks if m > seg), c.nb_segments)
        span = block_end - seg
        h = c.segment_start_hour(seg)
        h_mod = h % 24
        closest_hh = min((0, 6, 12, 18), key=lambda hm: min(abs(h_mod - hm), 24 - abs(h_mod - hm)))
        if first_block and abs(h_mod - closest_hh) * 60 > c.segment_duration * 60:
            label = ""
        else:
            label = f"{closest_hh:02d}h"
        first_block = False
        row1.append(f'<div style="grid-column:span {span}" class="th-tick-block">{label}</div>')
        seg = block_end

    # row2 : segment par segment, barre orange sur les pauses
    seg = 0
    while seg < c.nb_segments:
        if seg in inactive_range_starts:
            b = inactive_range_starts[seg]
            cs = b - seg
            row2.append(f'<div style="grid-column:span {cs}" class="th-seg-px th-pause-px"></div>')
            seg = b
        else:
            night_class = " th-seg-night" if seg in night_segs else ""
            row2.append(f'<div class="th-seg-px{night_class}"></div>')
            seg += 1

    header_row = "".join(row1) + "".join(row2)

    return header_row, rows_html


def _build_html_detail(solution):
    def row_class(rel):
        if rel["pinned"] is not None:
            return ' class="row-fixe"'
        if rel["solo"]:
            return ' class="row-solo"'
        if rel["partner"]:
            return ' class="row-binome"'
        return ""

    chrono_rows = []
    for entry in build_chrono_entries(solution.relays, solution.constraints):
        if isinstance(entry, ChronoRelay):
            e = entry
            flags = ", ".join(e.tags)
            chrono_rows.append(
                f'<tr{row_class(e.rel)}>'
                f'<td class="td-time td-nowrap">{e.day_s} {e.hh:02d}h{e.mm:02d} → {e.hh_end:02d}h{e.mm_end:02d}</td>'
                f'<td class="td-time td-right">{e.seg_start}</td>'
                f'<td class="td-time td-right">{e.km_start:.1f} km</td>'
                f'<td class="td-time td-right">{e.km_dist:.1f} km</td>'
                f'<td class="td-time td-right">{_fmt_dplus(e.d_plus)}</td>'
                f'<td class="td-time td-right">{_fmt_dmoins(e.d_moins)}</td>'
                f'<td class="td-time td-bold">{e.coureurs}</td>'
                f'<td class="td-time td-meta">{flags}</td>'
                f'</tr>'
            )
        else:
            p = entry
            chrono_rows.append(
                f'<tr class="row-pause">'
                f'<td class="td-pause td-nowrap">{p.ds} {p.hs:02d}h{p.ms:02d} → {p.de} {p.he:02d}h{p.me:02d}</td>'
                f'<td class="td-pause" colspan="7">⏸&nbsp; PAUSE {p.dur_str}</td>'
                f'</tr>'
            )

    chrono_html = (
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
                f'<tr{row_class(rl.rel)}>'
                f'<td class="td-recap td-nowrap">{rl.day_s} {rl.hh:02d}h{rl.mm:02d} → {rl.hh_e:02d}h{rl.mm_e:02d}</td>'
                f'<td class="td-recap td-right">{rl.km_dist:.1f} km</td>'
                f'<td class="td-recap td-right">{_fmt_dplus(rl.d_plus)}</td>'
                f'<td class="td-recap td-right">{_fmt_dmoins(rl.d_moins)}</td>'
                f'<td class="td-recap">{rl.partenaire}</td>'
                f'<td class="td-recap td-meta">{rl.repos_str}</td>'
                f'<td class="td-recap td-meta">{tags_str}</td>'
                f'</tr>'
            )

        dur_h = int(recap.total_duration_h)
        dur_m = int((recap.total_duration_h % 1) * 60)
        dur_str = f"{dur_h}h{dur_m:02d}"
        summary_row = (
            f'<tr class="row-summary">'
            f'<td class="td-recap td-summary td-nowrap">{recap.n_relais} relais &nbsp; {dur_str}</td>'
            f'<td class="td-recap td-summary td-right">{recap.total_km:.1f} km</td>'
            f'<td class="td-recap td-summary td-right">{_fmt_dplus(recap.total_d_plus)}</td>'
            f'<td class="td-recap td-summary td-right">{_fmt_dmoins(recap.total_d_moins)}</td>'
            f'<td class="td-recap td-summary td-meta" colspan="3">{flags_str.strip()}</td>'
            f'</tr>'
        )
        recap_sections.append(
            f'<h4 class="runner-title">{recap.name}</h4>'
            '<table class="detail-table">'
            '<tbody>' + summary_row + "\n" + "\n".join(detail_rows) + '</tbody>'
            '</table>'
        )

    recap_html = (
        '<h3 class="section-title">Par coureur</h3>'
        + "\n".join(recap_sections)
    )

    return chrono_html + "\n" + recap_html


# ------------------------------------------------------------------
# Export CSV
# ------------------------------------------------------------------


def _export_row(rel, constraints):
    c = constraints
    h_s = c.segment_start_hour(rel["start"])
    day_s = DAY_SHORT[min(int(h_s // 24), 2)]
    hh, mm = int(h_s) % 24, int((h_s % 1) * 60)
    h_e = c.segment_start_hour(rel["end"])
    hh_e, mm_e = int(h_e) % 24, int((h_e % 1) * 60)
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
    rows = [_export_row(rel, solution.constraints) for rel in solution.relays]
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def to_html(solution) -> str:
    """Retourne le planning complet en HTML (Gantt + planning détaillé)."""
    c = solution.constraints

    header_row, rows_html = _build_gantt(solution)

    profil_svg_row = ""
    if c.profil is not None:
        _pauses = [
            (c.time_seg_to_active(a) * c.segment_km, (b - a) * c.segment_duration)
            for a, b in c.inactive_ranges
        ]
        _svg = c.profil.to_svg(
            width=900,
            height=PROFIL_SVG_HEIGHT,
            padding_left=0,
            padding_right=0,
            padding_top=10,
            padding_bottom=30,
            speed_kmh=c.speed_kmh,
            pauses=_pauses if _pauses else None,
            inline=True,
        )
        _span = c.nb_segments
        profil_svg_row = (
            f'<div class="th-seg-label" style="vertical-align:bottom;font-size:10px;color:#555;"></div>'
            f'<div style="grid-column:span {_span};padding:0;">{_svg}</div>'
        )

    d = _summary_data(solution)

    text_section = _build_html_detail(solution)

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
<div class="gantt-container">
{profil_svg_row}
{header_row}
{"".join(rows_html)}
</div>
{text_section}
</body>
</html>"""
