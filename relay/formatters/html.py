
# TODO : add module docstring


from .commun import _seg_link_html, _fmt_deniv, _fmt_duration
from .commun import summary_data, build_chrono_entries,  build_runner_recaps


# configuration du gantt

TICK_STEP_H = 6      # Pas des ticks horaires (en heures)
ROW_HEIGHT = 22   # Hauteur d'une ligne coureur
OVERLAY_HEIGHT = 18   # Hauteur bandeau nuit/pause
PROFIL_SVG_HEIGHT = 140  # Hauteur du profil altimétrique 

# TRI_GANTT determine l'ordre des lignes dans le gantt
# "decl" = ordre des new_runner() - constant
# "alpha" = ordre alphabétique - constant
# "start" = par ordre de départ - variable selon solutions
TRI_GANTT = "decl"


GANTT_CSS = """
  /* Gantt : grille 2 colonnes (label | piste SVG) */
  .gantt-grid {
    display: grid;
    grid-template-columns: max-content 1fr;
    align-items: stretch;
  }
  .gh-label {
    padding: 1px 6px;
    white-space: nowrap;
    font-size: 11px;
    align-self: center;
  }
  .gh-runner-label {
    font-weight: bold;
    border-top: 1px solid #e0e0e0;
  }
  .gh-track {
    display: block;
    width: 100%;
    overflow: hidden;
    border-top: 1px solid #e0e0e0;
  }
  .gh-track svg { display: block; width: 100%; }
  .gh-hours  { border-top: none; }
  .gh-km     { border-top: none; }
  .gh-overlay { border-top: 2px solid #bbb; }
  .gh-profil { border-top: none; border-bottom: 1px solid #ccc; }
"""

# Couleurs de remplissage et bordure par type de relais
_SVG_COLORS = {
    "relay_binome": ("#43a047", "#2e7d32"),
    "relay_solo":   ("#ef9a9a", "#b71c1c"),
    "relay_fixe":   ("#7986cb", "#283593"),
    "rest":         ("#fff9e6", "#f9a825"),
    "unavail":      ("#b0bec5", "#546e7a"),
}


# ------------------------------------------------------------------
# Helpers internes
# ------------------------------------------------------------------


def _total_minutes(c) -> int:
    return c.cumul_temps[-1]


def _x(t_min: int | float, total_min: int) -> float:
    """Convertit une minute absolue en coordonnée X dans un viewBox 0..1000."""
    if total_min == 0:
        return 0.0
    return t_min / total_min * 1000.0


def _ticks(c) -> list[tuple[int, str, str | None]]:
    """Calcule les ticks horaires alignés sur les heures 0/6/12/18.

    Retourne [(minute_abs, label_heure, label_km_ou_None), ...].
    label_km est None si le tick tombe pendant une pause.
    """
    total_min = _total_minutes(c)
    pause_intervals = [
        (c.cumul_temps[after_pt], c.cumul_temps[after_pt] + round(dur_h * 60))
        for after_pt, dur_h in c._pauses if dur_h > 0
    ]
    step_min = round(TICK_STEP_H * 60)

    # Premier tick : prochaine heure multiple de TICK_STEP_H après le départ
    start_h_mod = c.start_hour % 24
    first_tick_h = (int(start_h_mod / TICK_STEP_H) + 1) * TICK_STEP_H
    first_tick_offset_min = round((first_tick_h - start_h_mod) * 60)

    result = []
    t = first_tick_offset_min
    while t <= total_min:
        h_abs = c.start_hour + t / 60.0
        h_mod = h_abs % 24
        hh = int(round(h_mod)) % 24
        label_h = f"{hh:02d}h"

        in_pause = any(ms < t < me for ms, me in pause_intervals)
        if in_pause:
            label_km = None
        else:
            best_pt = min(range(c.nb_points), key=lambda i: abs(c.cumul_temps[i] - t))
            label_km = f"{c.waypoints_km[best_pt]:.0f} km"

        result.append((t, label_h, label_km))
        t += step_min

    if not result or result[-1][0] < total_min:
        result.append((total_min, "", None))
    return result


def _relay_type(rel: dict) -> str:
    if rel.get("pinned"):
        return "relay_fixe"
    if rel.get("partner"):
        return "relay_binome"
    return "relay_solo"


def _unavail_time_ranges(c, runner: str) -> list[tuple[int, int]]:
    specs = c.runners_data[runner].relais
    if any(spec.window is None for spec in specs):
        return []
    # Les indices dans spec.window sont des indices internes (post-pause).
    # Les points fictifs de pause ne sont ni disponibles ni indisponibles —
    # on les ignore pour ne pas créer de fausses zones d'indisponibilité.
    pause_point_indices = {arc + 1 for arc in c.pause_arcs}
    avail_pts: set[int] = set()
    for spec in specs:
        for pt_lo, pt_hi in (spec.window or []):
            avail_pts.update(range(pt_lo, pt_hi + 1))
    unavail = []
    in_u = False
    start_pt = 0
    for pt in range(c.nb_points):
        if pt in pause_point_indices:
            continue
        if pt not in avail_pts:
            if not in_u:
                in_u = True
                start_pt = pt
        else:
            if in_u:
                unavail.append((c.cumul_temps[start_pt], c.cumul_temps[pt]))
                in_u = False
    if in_u:
        unavail.append((c.cumul_temps[start_pt], c.cumul_temps[c.nb_points - 1]))
    return unavail


# ------------------------------------------------------------------
# Construction des SVG / HTML
# ------------------------------------------------------------------


def _header_ticks_html(c, ticks: list) -> str:
    """Header 1 (heures) + Header 2 (km) — deux rangées label+SVG."""
    total_min = _total_minutes(c)

    def _svg(attr: str, font_size: int, height: int) -> str:
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="{height}"'
            f' preserveAspectRatio="none" viewBox="0 0 1000 {height}">'
        ]
        for t, lh, lkm in ticks:
            label = lh if attr == "h" else (lkm or "")
            if not label:
                continue
            xv = _x(t, total_min)
            parts.append(f'<line x1="{xv:.1f}" y1="0" x2="{xv:.1f}" y2="{height}" stroke="#bbb" stroke-width="1"/>')
            parts.append(f'<text x="{xv:.1f}" y="{height - 3}" font-size="{font_size}" fill="#444" text-anchor="middle">{label}</text>')
        parts.append("</svg>")
        return "".join(parts)

    return (
        '<div class="gh-label"></div>'
        f'<div class="gh-track gh-hours">{_svg("h", 9, 16)}</div>'
        '<div class="gh-label"></div>'
        f'<div class="gh-track gh-km">{_svg("km", 8, 14)}</div>'
    )


def _overlay_svg(c, ticks: list) -> str:
    """Header 3 : bandeaux nuit + pauses + lignes de tick."""
    total_min = _total_minutes(c)
    h = OVERLAY_HEIGHT

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="{h}"'
        f' preserveAspectRatio="none" viewBox="0 0 1000 {h}">'
    ]

    # Bandeaux nuit (un rectangle par intervalle, pas de fusion)
    for lo, hi in c._intervals_night:
        t_s = c.cumul_temps[lo]
        t_e = c.cumul_temps[hi]
        x1, x2 = _x(t_s, total_min), _x(t_e, total_min)
        parts.append(f'<rect x="{x1:.1f}" y="0" width="{x2 - x1:.1f}" height="{h}" fill="#c5cae9" opacity="0.7"/>')

    # Bandeaux pauses
    for after_point, duree_h in c._pauses:
        if duree_h <= 0:
            continue
        t_s = c.cumul_temps[after_point]
        t_e = t_s + round(duree_h * 60)
        x1, x2 = _x(t_s, total_min), _x(t_e, total_min)
        parts.append(f'<rect x="{x1:.1f}" y="0" width="{x2 - x1:.1f}" height="{h}" fill="#ff9800" opacity="0.85"/>')
        parts.append(f'<text x="{(x1 + x2) / 2:.1f}" y="{h - 4}" font-size="8" fill="#7f3000" text-anchor="middle">pause</text>')

    # Lignes de tick
    for t, _, _ in ticks:
        xv = _x(t, total_min)
        parts.append(f'<line x1="{xv:.1f}" y1="0" x2="{xv:.1f}" y2="{h}" stroke="#999" stroke-width="0.5"/>')

    parts.append("</svg>")
    return (
        '<div class="gh-label"></div>'
        f'<div class="gh-track gh-overlay">{"".join(parts)}</div>'
    )


def _runner_svg(c, relays_for_runner: list[dict], unavail_times: list[tuple[int, int]], ticks: list) -> str:
    """SVG dilatable représentant les relais d'un coureur."""
    total_min = _total_minutes(c)
    h = ROW_HEIGHT

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="{h}"'
        f' preserveAspectRatio="none" viewBox="0 0 1000 {h}">'
    ]
    parts.append(f'<rect x="0" y="0" width="1000" height="{h}" fill="#f8f8f8"/>')

    sorted_relays = sorted(relays_for_runner, key=lambda r: r["time_start_min"])

    for i, rel in enumerate(sorted_relays):
        rest_min_h = rel.get("rest_min_h")
        if rest_min_h is not None and rest_min_h > 0:
            t_s = rel["time_end_min"]
            t_e = t_s + round(rest_min_h * 60)
            # Clipper au début du relais suivant (ne pas déborder)
            if i + 1 < len(sorted_relays):
                t_e = min(t_e, sorted_relays[i + 1]["time_start_min"])
            x1, x2 = _x(t_s, total_min), _x(t_e, total_min)
            fill, stroke = _SVG_COLORS["rest"]
            parts.append(f'<rect x="{x1:.1f}" y="1" width="{x2 - x1:.1f}" height="{h - 2}" fill="{fill}" stroke="{stroke}" stroke-width="0.5"/>')

    for rel in sorted_relays:
        x1 = _x(rel["time_start_min"], total_min)
        x2 = _x(rel["time_end_min"], total_min)
        fill, stroke = _SVG_COLORS.get(_relay_type(rel), ("#cccccc", "#999"))
        parts.append(
            f'<rect x="{x1:.1f}" y="1" width="{x2 - x1:.1f}" height="{h - 2}"'
            f' fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
        )
        partner = rel.get("partner") or ""
        label = partner if partner else ("solo" if rel.get("solo") else "")
        if x2 - x1 > 20 and label:
            mid_x = (x1 + x2) / 2
            parts.append(
                f'<text x="{mid_x:.1f}" y="{h // 2 + 4}" font-size="7"'
                f' fill="#111" text-anchor="middle">{label}</text>'
            )

    for t_s, t_e in unavail_times:
        x1, x2 = _x(t_s, total_min), _x(t_e, total_min)
        fill, stroke = _SVG_COLORS["unavail"]
        parts.append(f'<rect x="{x1:.1f}" y="1" width="{x2 - x1:.1f}" height="{h - 2}" fill="{fill}" stroke="{stroke}" stroke-width="0.5"/>')

    for t, _, _ in ticks:
        xv = _x(t, total_min)
        parts.append(f'<line x1="{xv:.1f}" y1="0" x2="{xv:.1f}" y2="{h}" stroke="#bbb" stroke-width="0.5"/>')

    parts.append("</svg>")
    return "".join(parts)


def _profil_svg_row(solution) -> str:
    """Ligne SVG du profil altimétrique (axe X = temps), ou '' si absent."""
    c = solution.constraints
    if not c.parcours.has_profile:
        return ""
    pauses = [(c.waypoints_km[after_pt], dur_h) for after_pt, dur_h in c._pauses if dur_h > 0]

    # Indices de waypoints (numérotation interne avec pauses) utilisés dans la solution
    used_indices: set[int] = set()
    for rel in solution.relays:
        used_indices.add(rel["wp_start"])
        used_indices.add(rel["wp_end"])

    svg = c.parcours.svg_profile(
        width=900,
        height=PROFIL_SVG_HEIGHT,
        padding_left=0,
        padding_right=0,
        padding_top=10,
        padding_bottom=30,
        speed_kmh=c.speed_kmh,
        pauses=pauses if pauses else None,
        used_waypoint_indices=sorted(used_indices),
        inline=True,
    )
    return (
        '<div class="gh-label"></div>'
        f'<div class="gh-track gh-profil">{svg}</div>'
    )


# ------------------------------------------------------------------
# Point d'entrée public
# ------------------------------------------------------------------


def build_gantt(solution) -> str:
    """Retourne le div .gantt-grid complet (profil + headers + coureurs)."""
    c = solution.constraints
    tick_list = _ticks(c)

    by_runner: dict[str, list[dict]] = {r: [] for r in c.runners}
    for rel in solution.relays:
        by_runner[rel["runner"]].append(rel)

    def first_start(runner):
        rels = by_runner[runner]
        return min((r["time_start_min"] for r in rels), default=float("inf"))

    if TRI_GANTT == "alpha":
        runner_order = sorted(c.runners)
    elif TRI_GANTT == "start":
        runner_order = sorted(c.runners, key=first_start)
    else:
        runner_order = c.runners

    rows = []
    for r in runner_order:
        unavail = _unavail_time_ranges(c, r)
        svg = _runner_svg(c, by_runner[r], unavail, tick_list)
        rows.append(
            f'<div class="gh-label gh-runner-label">{r}</div>'
            f'<div class="gh-track">{svg}</div>'
        )

    inner = (
        _profil_svg_row(solution)
        + _header_ticks_html(c, tick_list)
        + _overlay_svg(c, tick_list)
        + "".join(rows)
    )
    return f'<div class="gantt-grid">\n{inner}\n</div>'

# ------------------------------------------------------------------
# Rendu HTML
# ------------------------------------------------------------------

def _row_class(rel):
    if rel["pinned"]:
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
                f'<td class="td-time td-right">{_seg_link_html(e.seg_start, e.rel)}</td>'
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
    # 10 colonnes : Coureur/Horaire | Seg. | Km | Dist. | Flex | Partenaire | D+ | D- | Repos | Tags
    N_COLS = 10

    header_cells = (
        '<div class="rc-cell rc-head">Coureur / Horaire</div>'
        '<div class="rc-cell rc-head rc-right">Seg.</div>'
        '<div class="rc-cell rc-head rc-right">Km</div>'
        '<div class="rc-cell rc-head rc-right">Dist.</div>'
        '<div class="rc-cell rc-head rc-right rc-meta">Flex</div>'
        '<div class="rc-cell rc-head">Partenaire</div>'
        '<div class="rc-cell rc-head rc-right">D+</div>'
        '<div class="rc-cell rc-head rc-right">D-</div>'
        '<div class="rc-cell rc-head rc-meta">Repos</div>'
        '<div class="rc-cell rc-head rc-meta">Tags</div>'
    )

    def _row_bg(rel):
        if rel["pinned"]:
            return " rc-fixe"
        if rel["solo"]:
            return " rc-solo"
        if rel["partner"]:
            return " rc-binome"
        return ""

    rows = []
    for recap in build_runner_recaps(solution.relays, solution.constraints):
        flags = []
        if recap.n_solo:
            flags.append(f"{recap.n_solo} seul")
        if recap.n_nuit:
            flags.append(f"{recap.n_nuit} nuit")
        flags_str = f"({', '.join(flags)})" if flags else ""

        dur_str = _fmt_duration(recap.total_duration_h)

        # Ligne résumé : nom du coureur dans la 1ère colonne, totaux dans les suivantes
        rows.append(
            f'<div class="rc-cell rc-summary rc-runner-name rc-nowrap">{recap.name} &nbsp;</div>'
            '<div class="rc-cell rc-summary"></div>'
            '<div class="rc-cell rc-summary"></div>'
            f'<div class="rc-cell rc-summary rc-right">{recap.total_km:.1f} km</div>'
            f'<div class="rc-cell rc-summary rc-right rc-meta">({recap.total_flex:+.1f})</div>'
            '<div class="rc-cell rc-summary"></div>'
            f'<div class="rc-cell rc-summary rc-right">{_fmt_deniv(recap.total_d_plus, "+")}</div>'
            f'<div class="rc-cell rc-summary rc-right">{_fmt_deniv(recap.total_d_moins, "-")}</div>'
            '<div class="rc-cell rc-summary rc-meta"></div>'
            f'<div class="rc-cell rc-summary rc-meta">{flags_str}</div>'
        )

        # Lignes de relais
        for rl in recap.relais:
            tags_str = ", ".join(rl.tags)
            bg = _row_bg(rl.rel)
            rows.append(
                f'<div class="rc-cell rc-nowrap{bg}">{rl.day_s} {rl.hh:02d}h{rl.mm:02d} → {rl.hh_e:02d}h{rl.mm_e:02d}</div>'
                f'<div class="rc-cell rc-right{bg}">{_seg_link_html(rl.seg_start, rl.rel)}</div>'
                f'<div class="rc-cell rc-right{bg}">{rl.km_start:.1f} km</div>'
                f'<div class="rc-cell rc-right{bg}">{rl.km_dist:.1f} km</div>'
                f'<div class="rc-cell rc-right rc-meta{bg}">{rl.flex_str}</div>'
                f'<div class="rc-cell{bg}">{rl.partenaire}</div>'
                f'<div class="rc-cell rc-right{bg}">{_fmt_deniv(rl.d_plus, "+")}</div>'
                f'<div class="rc-cell rc-right{bg}">{_fmt_deniv(rl.d_moins, "-")}</div>'
                f'<div class="rc-cell rc-meta{bg}">{rl.repos_str}</div>'
                f'<div class="rc-cell rc-meta{bg}">{tags_str}</div>'
            )

        # Ligne vide séparatrice (fond blanc)
        rows.append(
            '<div class="rc-cell rc-sep"></div>' * N_COLS
        )

    return (
        '<h3 class="section-title">Par coureur</h3>'
        '<div class="recap-grid">'
        + header_cells
        + "\n".join(rows)
        + "</div>"
    )


def _html_ub_str(d: dict) -> str:
    """Formate les bornes du score et des solos pour l'en-tête HTML."""
    parts = []
    if d["ub_score_target"] is not None:
        parts.append(f'<span title="Majorant heuristique (taille=target)">≤{d["ub_score_target"]}</span>')
    if d["lb_solos"] is not None:
        parts.append(f'<span title="Borne basse solos (heuristique)">solos≥{d["lb_solos"]}</span>')
    if not parts:
        return ""
    return ' &nbsp;<span style="color:#888;font-size:11px">' + " / ".join(parts) + "</span>"


def to_html(solution) -> str:
    """Retourne le planning complet en HTML (Gantt + planning détaillé)."""
    c = solution.constraints
    d = summary_data(solution)

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Planning {c.total_km} km</title>
<style>
  body {{ font-family: sans-serif; font-size: 12px; margin: 16px auto; max-width: 1200px; }}
  table {{ border-collapse: collapse; table-layout: fixed; }}
  th, td {{ padding: 2px; }}
{GANTT_CSS}
  /* Tables de détail */
  .detail-table {{ border-collapse: collapse; font-size: 12px; table-layout: auto; }}
  .section-title {{ margin-top: 2em; }}
  .thead-row {{ background: #eee; font-weight: bold; }}
  .th-detail {{ padding: 4px 8px; text-align: left; }}
  .th-detail.th-right {{ text-align: right; }}

  /* Lignes colorées (tableau chrono) */
  .row-solo   {{ background: #fdf3f3; }}
  .row-binome {{ background: #f1f8f1; }}
  .row-fixe   {{ background: #f0f1fa; }}
  .row-pause  {{ background: #fff3e0; }}
  .td-pause   {{ color: #e65100; font-weight: bold; padding: 4px 8px; }}

  /* Cellules de détail chrono */
  .td-time   {{ padding: 3px 8px; }}
  .td-nowrap {{ white-space: nowrap; }}
  .td-right  {{ text-align: right; }}
  .td-bold   {{ font-weight: bold; }}
  .td-meta   {{ color: #888; font-size: 11px; }}
  .td-summary {{ font-weight: bold; background: #f5f5f5; }}

  /* Grid récap coureurs */
  .recap-grid {{
    display: grid;
    grid-template-columns: repeat(10, max-content);
    font-size: 12px;
    margin-top: 0.5em;
  }}
  .rc-cell {{ padding: 2px 8px; white-space: nowrap; }}
  .rc-runner-name {{ font-weight: bold; min-width: 7em; }}
  .rc-head {{ font-weight: bold; background: #eee; padding: 4px 8px; }}
  .rc-right {{ text-align: right; }}
  .rc-nowrap {{ white-space: nowrap; }}
  .rc-meta {{ color: #888; font-size: 11px; }}
  .rc-summary {{ font-weight: bold; background: #f5f5f5; }}
  .rc-sep {{ background: #fff; padding: 4px 0; border: none; }}
  .rc-solo   {{ background: #fdf3f3; }}
  .rc-binome {{ background: #f1f8f1; }}
  .rc-fixe   {{ background: #f0f1fa; }}
</style>
</head>
<body>
<h2>Planning &nbsp; {c.total_km:.1f} km &nbsp;|&nbsp; {d['day_start']} {d['hh_start']:02d}h{d['mm_start']:02d} → {d['day_end']} {d['hh_end']:02d}h{d['mm_end']:02d}</h2>
<p>{d['nb_coureurs']} coureurs &nbsp;|&nbsp; {d['km_engages']:.1f} km engagés &nbsp;|&nbsp; {d['nb_points']} points &nbsp;|&nbsp; {d['min_per_km_str']} min/km</p>
<p>Score <strong>{d['score_str']}</strong>{_html_ub_str(d)} &nbsp;|&nbsp; solos <strong>{d['n_solos']}</strong> ({d['km_solo']:.1f} km) &nbsp;|&nbsp; flex <strong>+{d['flex_plus_str']} / -{d['flex_moins_str']} km</strong></p>
<p>
  <span style="background:#43a047;padding:2px 8px;border:1px solid #2e7d32;">Duo</span>&nbsp;
  <span style="background:#ef9a9a;padding:2px 8px;border:1px solid #b71c1c;">Solo</span>&nbsp;
  <span style="background:#7986cb;padding:2px 8px;border:1px solid #283593;color:#fff;">Épinglé</span>&nbsp;
  <span style="background:#b0bec5;padding:2px 8px;border:1px solid #546e7a;">Indisponible</span>&nbsp;
  <span style="background:#fff9e6;padding:2px 8px;border:1px solid #f9a825;">Repos</span>&nbsp;
  <span style="background:#c5cae9;padding:2px 8px;border:1px solid #7986cb;">Nuit</span>&nbsp;
  <span style="background:#ff9800;padding:2px 8px;border:1px solid #e65100;">Pause</span>
</p>
{build_gantt(solution)}
{_build_html_chrono(solution)}
{_build_html_recap(solution)}
</body>
</html>"""

