#!/usr/bin/env python3
"""
Analyse des solutions énumérées dans enumerate_solutions/
Pour chaque coureur :
  - histogramme PNG : nb de solutions couvrant chaque segment élémentaire
  - page HTML : contraintes du coureur + histogramme
Page HTML de synthèse avec liens vers chaque coureur.
Sorties dans : explore_solutions/
"""

import csv

import sys

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from data import (
    RUNNERS_DATA,
    MATCHING_CONSTRAINTS,
    TOTAL_KM,
    N_SEGMENTS,
    SEGMENT_KM,
    SPEED_KMH,
    SEGMENT_DURATION_H,
    START_HOUR,
    REST_NORMAL,
    REST_NIGHT,
    segment_start_hour,
    NIGHT_SEGMENTS,
)
from compat import is_compatible

OUT_DIR = Path("explore_solutions")


# ── Chargement des solutions ──────────────────────────────────────────────────


def load_solutions(folder="enumerate_solutions"):
    solutions = []
    for path in sorted(Path(folder).glob("run_*_config_*.csv")):
        relays = []
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                relays.append(
                    {
                        "coureur": row["coureur"],
                        "partenaire": row["partenaire"],
                        "km_debut": int(row["km_debut"]),
                        "km_fin": int(row["km_fin"]),
                        "jour": row["jour"],
                        "debut": row["debut"],
                        "fin": row["fin"],
                        "solo": row["solo"],
                        "nuit": row["nuit"],
                    }
                )
        solutions.append(relays)
    return solutions


# ── Calcul de la couverture par segment et par coureur ────────────────────────


def segment_coverage(solutions, runner):
    """
    Pour chaque segment élémentaire (0..N_SEGMENTS-1),
    retourne deux tableaux : nombre de solutions où le coureur court ce segment
    en solo, et en binôme.
    """
    counts_solo = np.zeros(N_SEGMENTS, dtype=int)
    counts_binome = np.zeros(N_SEGMENTS, dtype=int)
    for relays in solutions:
        for r in relays:
            if r["coureur"] == runner:
                seg_start = r["km_debut"] // SEGMENT_KM
                seg_end = r["km_fin"] // SEGMENT_KM
                if r["solo"] == "oui":
                    counts_solo[seg_start:seg_end] += 1
                else:
                    counts_binome[seg_start:seg_end] += 1
    return counts_solo, counts_binome


# ── Axe X : étiquettes "km / jour+heure" ─────────────────────────────────────

_DAY_NAMES = ["Mer", "Jeu", "Ven", "Sam"]


def x_labels(segments):
    """Retourne les étiquettes courtes pour chaque segment (km + jour heure)."""
    labels = []
    for s in segments:
        km = s * SEGMENT_KM
        h_abs = segment_start_hour(s)
        day_idx = int(h_abs // 24)
        hh = int(h_abs % 24)
        day = _DAY_NAMES[day_idx] if day_idx < len(_DAY_NAMES) else f"J+{day_idx}"
        labels.append(f"{km} km\n{day} {hh:02d}h")
    return labels


# ── Calcul des débuts de relais par longueur ─────────────────────────────────


def relay_start_coverage(solutions, runner):
    """
    Pour chaque segment de départ, retourne un dict {taille_km: np.array(N_SEGMENTS)}
    comptant le nombre de solutions où le coureur commence un relais de cette longueur
    à ce segment.
    """
    relay_sizes_km = sorted(set(s * SEGMENT_KM for s in RUNNERS_DATA[runner].relais))
    counts = {km: np.zeros(N_SEGMENTS, dtype=int) for km in relay_sizes_km}
    for relays in solutions:
        for r in relays:
            if r["coureur"] == runner:
                seg_start = r["km_debut"] // SEGMENT_KM
                relay_km = r["km_fin"] - r["km_debut"]
                if relay_km in counts:
                    counts[relay_km][seg_start] += 1
    return counts


# ── Utilitaire : hachuri d'indisponibilité ────────────────────────────────────


def _draw_unavailability(ax, runner, seg_min, seg_max):
    """Superpose un fond hachuré (///) sur les périodes d'indisponibilité du coureur."""
    for us, ue in unavailable_segments(runner):
        xs = max(us, seg_min) - 0.5
        xe = min(ue, seg_max + 1) - 0.5
        if xs < xe:
            ax.axvspan(xs, xe, facecolor="none", edgecolor="#c0392b",
                       hatch="///", alpha=0.35, zorder=1)


# ── Génération de l'histogramme PNG ───────────────────────────────────────────


def make_histogram(runner, counts_solo, counts_binome, n_solutions, out_path):
    counts = counts_solo + counts_binome
    active = np.where(counts > 0)[0]
    if len(active) == 0:
        # Aucune présence — image vide avec message
        fig, ax = plt.subplots(figsize=(6, 3))
        ax.text(
            0.5,
            0.5,
            "Aucun segment couvert",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=14,
            color="gray",
        )
        ax.axis("off")
        fig.savefig(out_path, dpi=100, bbox_inches="tight")
        plt.close(fig)
        return

    seg_min, seg_max = 0, N_SEGMENTS - 1
    segs = np.arange(seg_min, seg_max + 1)
    vals_binome = counts_binome[seg_min : seg_max + 1]
    vals_solo = counts_solo[seg_min : seg_max + 1]

    fig_w = max(10, N_SEGMENTS * 0.4)
    fig, ax = plt.subplots(figsize=(fig_w, 4))

    ax.bar(segs, vals_binome, color="#3498db", edgecolor="white", linewidth=0.5, label="Binôme")
    ax.bar(segs, vals_solo, bottom=vals_binome, color="#2ecc71", edgecolor="white", linewidth=0.5, label="Solo")

    ax.set_xlim(seg_min - 0.5, seg_max + 0.5)
    ax.set_ylim(0, n_solutions + 1)

    # Fond gris clair sur les périodes de nuit (regrouper les segments contigus)
    night_in_range = sorted(s for s in NIGHT_SEGMENTS if seg_min <= s <= seg_max)
    if night_in_range:
        groups, start = [], night_in_range[0]
        for prev, curr in zip(night_in_range, night_in_range[1:]):
            if curr != prev + 1:
                groups.append((start, prev))
                start = curr
        groups.append((start, night_in_range[-1]))
        for gs, ge in groups:
            ax.axvspan(gs - 0.5, ge + 0.5, color="#dddddd", alpha=0.5, zorder=0)
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.axhline(
        n_solutions,
        color="#e74c3c",
        linewidth=1,
        linestyle="--",
        label=f"Total solutions ({n_solutions})",
    )

    # Ticks uniquement sur les multiples de 10 km
    km_step = 10  # km entre chaque tick
    seg_step = km_step // SEGMENT_KM
    tick_segs = np.arange(
        (seg_min // seg_step) * seg_step,
        seg_max + seg_step,
        seg_step,
        dtype=int,
    )
    tick_segs = tick_segs[(tick_segs >= seg_min) & (tick_segs <= seg_max)]
    ax.set_xticks(tick_segs)
    ax.set_xticklabels(x_labels(tick_segs), fontsize=7)

    ax.set_xlabel("Position (km / heure de départ)", fontsize=9)
    ax.set_ylabel("Nombre de solutions", fontsize=9)
    ax.set_title(f"{runner} — présence par segment élémentaire", fontsize=11)

    # Légende couleurs
    from matplotlib.patches import Patch

    _draw_unavailability(ax, runner, seg_min, seg_max)

    legend_elements = [
        Patch(facecolor="#3498db", label="Binôme"),
        Patch(facecolor="#2ecc71", label="Solo"),
        Patch(facecolor="#dddddd", alpha=0.5, label="Période de nuit (0h–6h)"),
    ]
    if unavailable_segments(runner):
        legend_elements.append(
            Patch(facecolor="none", edgecolor="#c0392b", hatch="///", alpha=0.35, label="Indisponible")
        )
    ax.legend(handles=legend_elements, fontsize=8, loc="upper right")

    fig.tight_layout()
    fig.savefig(out_path, dpi=100, bbox_inches="tight")
    plt.close(fig)


# ── Histogramme des débuts de relais par longueur ────────────────────────────

_RELAY_COLORS = {
    10: "#2ecc71",   # vert
    15: "#3498db",   # bleu
    20: "#e74c3c",   # rouge
    30: "#9b59b6",   # violet
}
_RELAY_COLOR_DEFAULT = "#95a5a6"  # gris pour toute autre longueur


def make_relay_start_histogram(runner, relay_counts, n_solutions, out_path):
    """
    Histogramme empilé : pour chaque segment de départ, nombre de solutions
    par longueur de relais. Axe X fixe couvrant toute la course.
    """
    seg_min, seg_max = 0, N_SEGMENTS - 1
    segs = np.arange(seg_min, seg_max + 1)
    relay_sizes = sorted(relay_counts.keys())

    fig_w = max(10, N_SEGMENTS * 0.4)
    fig, ax = plt.subplots(figsize=(fig_w, 4))

    bottom = np.zeros(len(segs), dtype=float)
    for km in relay_sizes:
        vals = relay_counts[km][seg_min: seg_max + 1].astype(float)
        color = _RELAY_COLORS.get(km, _RELAY_COLOR_DEFAULT)
        ax.bar(segs, vals, bottom=bottom, color=color, edgecolor="white",
               linewidth=0.5, label=f"{km} km")
        bottom += vals

    ax.set_xlim(seg_min - 0.5, seg_max + 0.5)
    ax.set_ylim(0, n_solutions + 1)

    # Fond gris sur les nuits
    night_in_range = sorted(s for s in NIGHT_SEGMENTS if seg_min <= s <= seg_max)
    if night_in_range:
        groups, start = [], night_in_range[0]
        for prev, curr in zip(night_in_range, night_in_range[1:]):
            if curr != prev + 1:
                groups.append((start, prev))
                start = curr
        groups.append((start, night_in_range[-1]))
        for gs, ge in groups:
            ax.axvspan(gs - 0.5, ge + 0.5, color="#dddddd", alpha=0.5, zorder=0)

    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.axhline(n_solutions, color="#e74c3c", linewidth=1, linestyle="--",
               label=f"Total solutions ({n_solutions})")

    km_step = 10
    seg_step = km_step // SEGMENT_KM
    tick_segs = np.arange(
        (seg_min // seg_step) * seg_step,
        seg_max + seg_step,
        seg_step,
        dtype=int,
    )
    tick_segs = tick_segs[(tick_segs >= seg_min) & (tick_segs <= seg_max)]
    ax.set_xticks(tick_segs)
    ax.set_xticklabels(x_labels(tick_segs), fontsize=7)

    ax.set_xlabel("Position (km / heure de départ)", fontsize=9)
    ax.set_ylabel("Nombre de solutions", fontsize=9)
    ax.set_title(f"{runner} — début de relais par longueur", fontsize=11)

    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor=_RELAY_COLORS.get(km, _RELAY_COLOR_DEFAULT), label=f"{km} km")
        for km in relay_sizes
    ]
    legend_elements.append(Patch(facecolor="#dddddd", alpha=0.5, label="Période de nuit (0h–6h)"))
    _draw_unavailability(ax, runner, seg_min, seg_max)
    if unavailable_segments(runner):
        legend_elements.append(
            Patch(facecolor="none", edgecolor="#c0392b", hatch="///", alpha=0.35, label="Indisponible")
        )
    ax.legend(handles=legend_elements, fontsize=8, loc="upper right")

    fig.tight_layout()
    fig.savefig(out_path, dpi=100, bbox_inches="tight")
    plt.close(fig)


# ── Diversité : coureurs distincts par segment ────────────────────────────────


def segment_runner_diversity(solutions):
    """
    Pour chaque segment élémentaire, retourne le nombre de coureurs distincts
    qui l'ont couvert dans au moins une solution.
    """
    runners_per_seg = [set() for _ in range(N_SEGMENTS)]
    for relays in solutions:
        for r in relays:
            seg_start = r["km_debut"] // SEGMENT_KM
            seg_end = r["km_fin"] // SEGMENT_KM
            for s in range(seg_start, seg_end):
                runners_per_seg[s].add(r["coureur"])
    return np.array([len(s) for s in runners_per_seg], dtype=int)


def make_diversity_histogram(diversity, out_path):
    active = np.where(diversity > 0)[0]
    if len(active) == 0:
        return
    seg_min, seg_max = int(active[0]), int(active[-1])
    segs = np.arange(seg_min, seg_max + 1)
    vals = diversity[seg_min : seg_max + 1]
    n_runners = int(diversity.max())

    fig_w = max(14, len(segs) * 0.18)
    fig, ax = plt.subplots(figsize=(fig_w, 4))

    colors = ["#2ecc71" if v == 1 else "#3498db" if v <= 3 else "#e67e22" if v <= 6 else "#e74c3c" for v in vals]
    ax.bar(segs, vals, color=colors, edgecolor="white", linewidth=0.3)

    # Fond gris sur les nuits
    night_in_range = sorted(s for s in NIGHT_SEGMENTS if seg_min <= s <= seg_max)
    if night_in_range:
        groups, start = [], night_in_range[0]
        for prev, curr in zip(night_in_range, night_in_range[1:]):
            if curr != prev + 1:
                groups.append((start, prev))
                start = curr
        groups.append((start, night_in_range[-1]))
        for gs, ge in groups:
            ax.axvspan(gs - 0.5, ge + 0.5, color="#dddddd", alpha=0.5, zorder=0)

    ax.set_xlim(seg_min - 0.5, seg_max + 0.5)
    ax.set_ylim(0, n_runners + 1)
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))

    km_step = 10
    seg_step = km_step // SEGMENT_KM
    tick_segs = np.arange(
        (seg_min // seg_step) * seg_step,
        seg_max + seg_step,
        seg_step,
        dtype=int,
    )
    tick_segs = tick_segs[(tick_segs >= seg_min) & (tick_segs <= seg_max)]
    ax.set_xticks(tick_segs)
    ax.set_xticklabels(x_labels(tick_segs), fontsize=7)

    ax.set_xlabel("Position (km / heure de départ)", fontsize=9)
    ax.set_ylabel("Nombre de coureurs distincts", fontsize=9)
    ax.set_title("Diversité des coureurs par segment élémentaire", fontsize=11)

    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#2ecc71", label="1 coureur possible"),
        Patch(facecolor="#3498db", label="2–3 coureurs possibles"),
        Patch(facecolor="#e67e22", label="4–6 coureurs possibles"),
        Patch(facecolor="#e74c3c", label="7+ coureurs possibles"),
        Patch(facecolor="#dddddd", alpha=0.5, label="Période de nuit (0h–6h)"),
    ]
    ax.legend(handles=legend_elements, fontsize=8, loc="upper right")

    fig.tight_layout()
    fig.savefig(out_path, dpi=100, bbox_inches="tight")
    plt.close(fig)


def make_diversity_page(diversity, n_solutions, img_name, out_html):
    n_fixed = int(np.sum(diversity == 1))
    n_flex = int(np.sum(diversity > 1))
    max_div = int(diversity.max())

    stats_html = f"""<div class="stats">
  <strong>{n_fixed}</strong> segments avec un seul coureur possible (fixé dans toutes les solutions).
  <strong>{n_flex}</strong> segments avec plusieurs coureurs possibles.
  Maximum : <strong>{max_div}</strong> coureurs distincts sur un même segment.
</div>"""

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>Diversité par segment</title>
  <style>{CSS}</style>
</head>
<body>
  <nav><a href="index.html">← Retour à la synthèse</a></nav>
  <h1>Diversité des coureurs par segment</h1>
  <p>Pour chaque segment élémentaire (5 km), nombre de coureurs distincts
     ayant couvert ce segment dans au moins une des {n_solutions} solutions énumérées.</p>
  {stats_html}
  <div class="histogram">
    <img src="{img_name}" alt="Histogramme diversité">
  </div>
</body>
</html>
"""
    out_html.write_text(html, encoding="utf-8")


# ── Solo vs binôme global par segment ─────────────────────────────────────────


def segment_solo_binome(solutions):
    """
    Pour chaque segment élémentaire, retourne deux tableaux :
    - nombre total de passages solo (sur toutes les solutions et tous les coureurs)
    - nombre total de passages en binôme
    """
    counts_solo = np.zeros(N_SEGMENTS, dtype=int)
    counts_binome = np.zeros(N_SEGMENTS, dtype=int)
    for relays in solutions:
        for r in relays:
            seg_start = r["km_debut"] // SEGMENT_KM
            seg_end = r["km_fin"] // SEGMENT_KM
            if r["solo"] == "oui":
                counts_solo[seg_start:seg_end] += 1
            else:
                counts_binome[seg_start:seg_end] += 1
    return counts_solo, counts_binome


def make_solo_binome_histogram(counts_solo, counts_binome, out_path):
    counts = counts_solo + counts_binome
    active = np.where(counts > 0)[0]
    seg_min, seg_max = int(active[0]), int(active[-1])
    segs = np.arange(seg_min, seg_max + 1)
    vals_binome = counts_binome[seg_min : seg_max + 1]
    vals_solo = counts_solo[seg_min : seg_max + 1]
    y_max = int(counts[seg_min : seg_max + 1].max())

    fig_w = max(14, len(segs) * 0.18)
    fig, ax = plt.subplots(figsize=(fig_w, 4))

    ax.bar(segs, vals_binome, color="#3498db", edgecolor="white", linewidth=0.3, label="Binôme")
    ax.bar(segs, vals_solo, bottom=vals_binome, color="#2ecc71", edgecolor="white", linewidth=0.3, label="Solo")

    # Fond gris sur les nuits
    night_in_range = sorted(s for s in NIGHT_SEGMENTS if seg_min <= s <= seg_max)
    if night_in_range:
        groups, start = [], night_in_range[0]
        for prev, curr in zip(night_in_range, night_in_range[1:]):
            if curr != prev + 1:
                groups.append((start, prev))
                start = curr
        groups.append((start, night_in_range[-1]))
        for gs, ge in groups:
            ax.axvspan(gs - 0.5, ge + 0.5, color="#dddddd", alpha=0.5, zorder=0)

    ax.set_xlim(seg_min - 0.5, seg_max + 0.5)
    ax.set_ylim(0, y_max + 1)
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))

    km_step = 10
    seg_step = km_step // SEGMENT_KM
    tick_segs = np.arange(
        (seg_min // seg_step) * seg_step,
        seg_max + seg_step,
        seg_step,
        dtype=int,
    )
    tick_segs = tick_segs[(tick_segs >= seg_min) & (tick_segs <= seg_max)]
    ax.set_xticks(tick_segs)
    ax.set_xticklabels(x_labels(tick_segs), fontsize=7)

    ax.set_xlabel("Position (km / heure de départ)", fontsize=9)
    ax.set_ylabel("Nombre de passages (toutes solutions)", fontsize=9)
    ax.set_title("Répartition solo / binôme par segment élémentaire", fontsize=11)

    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#3498db", label="Binôme"),
        Patch(facecolor="#2ecc71", label="Solo"),
        Patch(facecolor="#dddddd", alpha=0.5, label="Période de nuit (0h–6h)"),
    ]
    ax.legend(handles=legend_elements, fontsize=8, loc="upper right")

    fig.tight_layout()
    fig.savefig(out_path, dpi=100, bbox_inches="tight")
    plt.close(fig)


def make_solo_binome_page(counts_solo, counts_binome, n_solutions, img_name, out_html):
    total_solo = int(counts_solo.sum())
    total_binome = int(counts_binome.sum())
    total = total_solo + total_binome
    pct_solo = 100 * total_solo / total if total else 0

    stats_html = f"""<div class="stats">
  Sur l'ensemble des solutions et des coureurs :
  <strong>{total_binome}</strong> passages en binôme ({100 - pct_solo:.1f} %)
  et <strong>{total_solo}</strong> passages en solo ({pct_solo:.1f} %).
</div>"""

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>Solo vs binôme par segment</title>
  <style>{CSS}</style>
</head>
<body>
  <nav><a href="index.html">← Retour à la synthèse</a></nav>
  <h1>Solo vs binôme par segment</h1>
  <p>Pour chaque segment élémentaire (5 km), nombre total de passages en solo
     et en binôme, agrégé sur toutes les solutions ({n_solutions}) et tous les coureurs.</p>
  {stats_html}
  <div class="histogram">
    <img src="{img_name}" alt="Histogramme solo vs binôme">
  </div>
</body>
</html>
"""
    out_html.write_text(html, encoding="utf-8")


# ── Infos contraintes d'un coureur ────────────────────────────────────────────


def unavailable_segments(runner):
    """
    Retourne la liste de plages (start, end) où le coureur est indisponible,
    calculée comme le complément des fenêtres de dispo (RUNNERS_DATA[runner].dispo) sur [0, N_SEGMENTS].
    Si le coureur n'a pas de fenêtre de dispo, il est disponible partout → [].
    """
    if not RUNNERS_DATA[runner].dispo:
        return []
    avail = sorted(RUNNERS_DATA[runner].dispo)
    unavail = []
    cursor = 0
    for a_start, a_end in avail:
        if cursor < a_start:
            unavail.append((cursor, a_start))
        cursor = max(cursor, a_end)
    if cursor < N_SEGMENTS:
        unavail.append((cursor, N_SEGMENTS))
    return unavail


def format_unavailability(runner):
    periods = unavailable_segments(runner)
    if not periods:
        return "Disponible sur toute la course"
    lines = []
    for s, e in periods:
        h_s = segment_start_hour(s)
        if e >= N_SEGMENTS:
            lines.append(
                f"Indisponible à partir du segment {s} (≈ {h_s:.1f}h après départ)"
            )
        else:
            h_e = segment_start_hour(e)
            lines.append(
                f"Indisponible seg {s}–{e} (≈ {h_s:.1f}h – {h_e:.1f}h après départ)"
            )
    return " ; ".join(lines)


def runner_constraints_html(runner):
    relays_seg = RUNNERS_DATA[runner].relais
    relays_km = [s * SEGMENT_KM for s in relays_seg]
    compatible = sorted(r for r in RUNNERS_DATA if r != runner and is_compatible(runner, r))
    mandatory = [f"{a}+{b}" for a, b in MATCHING_CONSTRAINTS["pair_at_least_once"] if runner in (a, b)]
    multi_night = RUNNERS_DATA[runner].nuit_max > 1

    rows = []

    # Relais engagés
    relay_str = ", ".join(f"{k} km" for k in relays_km)
    rows.append(
        ("Relais engagés", relay_str)
    )

    # Compatibilités
    rows.append(
        ("Coureurs compatibles (binômes)", ", ".join(compatible) if compatible else "—")
    )

    # Paires obligatoires
    rows.append(("Paires obligatoires", ", ".join(mandatory) if mandatory else "—"))

    # Disponibilité
    rows.append(("Disponibilité", format_unavailability(runner)))

    # Nuits multiples
    rows.append(("Plusieurs nuits autorisées", "Oui" if multi_night else "Non"))

    html = '<table class="constraints">\n'
    for label, value in rows:
        html += f"  <tr><th>{label}</th><td>{value}</td></tr>\n"
    html += "</table>\n"
    return html


# ── Page HTML par coureur ─────────────────────────────────────────────────────

CSS = """
body { font-family: sans-serif; max-width: 1100px; margin: 2em auto; color: #222; }
h1 { border-bottom: 2px solid #3498db; padding-bottom: 0.3em; }
h2 { color: #3498db; margin-top: 1.5em; }
table.constraints { border-collapse: collapse; width: 100%; margin: 1em 0; }
table.constraints th, table.constraints td {
    border: 1px solid #ddd; padding: 0.5em 0.8em; text-align: left; }
table.constraints th { background: #eaf4fb; width: 240px; }
.histogram img { max-width: 100%; border: 1px solid #ddd; border-radius: 4px; }
.stats { background: #f8f9fa; border-left: 4px solid #3498db;
         padding: 0.8em 1.2em; margin: 1em 0; }
a { color: #3498db; }
nav { margin-bottom: 1.5em; }
"""


def make_runner_page(runner, counts_solo, counts_binome, n_solutions, img_name, img_relay_name, out_html):
    constraints_html = runner_constraints_html(runner)
    counts = counts_solo + counts_binome

    # Stats de présence
    active_segs = int(np.sum(counts > 0))
    always_segs = int(np.sum(counts == n_solutions))
    sometimes_segs = active_segs - always_segs
    max_count = int(counts.max()) if active_segs > 0 else 0

    stats_html = f"""<div class="stats">
  <strong>Présence :</strong>
  {active_segs} segments couverts au moins une fois
  — dont <strong>{always_segs}</strong> dans <em>toutes</em> les solutions
  et <strong>{sometimes_segs}</strong> dans certaines seulement.
  Maximum : {max_count}/{n_solutions} solutions.
</div>"""

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>{runner}</title>
  <style>{CSS}</style>
</head>
<body>
  <nav><a href="index.html">← Retour à la synthèse</a></nav>
  <h1>{runner}</h1>

  <h2>Contraintes</h2>
  {constraints_html}

  <h2>Couverture par segment ({n_solutions} solutions)</h2>
  {stats_html}
  <div class="histogram">
    <img src="{img_name}" alt="Histogramme {runner}">
  </div>

  <h2>Début de relais par longueur ({n_solutions} solutions)</h2>
  <div class="histogram">
    <img src="{img_relay_name}" alt="Débuts de relais {runner}">
  </div>
</body>
</html>
"""
    out_html.write_text(html, encoding="utf-8")


# ── Page de synthèse ──────────────────────────────────────────────────────────


def _params_html():
    """Génère un tableau HTML des paramètres généraux du problème."""
    total_duration_h = N_SEGMENTS * SEGMENT_DURATION_H
    arr_h_abs = START_HOUR + total_duration_h
    arr_day_idx = int(arr_h_abs // 24)
    arr_hh = int(arr_h_abs % 24)
    arr_mm = int((arr_h_abs % 1) * 60) if arr_h_abs % 1 else 0
    day_names = ["Mercredi", "Jeudi", "Vendredi", "Samedi"]
    arr_day = day_names[arr_day_idx] if arr_day_idx < len(day_names) else f"J+{arr_day_idx}"
    seg_dur_min = SEGMENT_DURATION_H * 60

    rest_normal_h = REST_NORMAL * SEGMENT_DURATION_H
    rest_night_h = REST_NIGHT * SEGMENT_DURATION_H

    total_km_engaged = sum(sum(c.relais) * SEGMENT_KM for c in RUNNERS_DATA.values())
    n_runners = len(RUNNERS_DATA)

    params = [
        ("Parcours", f"Lyon → Fessenheim, {TOTAL_KM} km"),
        ("Départ", f"Mercredi {START_HOUR:02d}h00"),
        ("Arrivée estimée", f"{arr_day} {arr_hh:02d}h{arr_mm:02d}"),
        ("Durée totale estimée", f"{total_duration_h:.1f} h"),
        ("Vitesse moyenne", f"{SPEED_KMH} km/h"),
        ("Segments élémentaires", f"{N_SEGMENTS} × {SEGMENT_KM} km ({seg_dur_min:.0f} min/segment)"),
        ("Nombre de coureurs", str(n_runners)),
        ("Distance totale engagée", f"{total_km_engaged} km (pour {TOTAL_KM} km à couvrir)"),
        ("Repos après relais de jour", f"{REST_NORMAL} segments ({rest_normal_h:.1f} h)"),
        ("Repos après relais de nuit", f"{REST_NIGHT} segments ({rest_night_h:.1f} h)"),
        ("Période de nuit", "0h – 6h"),
    ]

    html = '<table class="constraints">\n'
    for label, value in params:
        html += f"  <tr><th>{label}</th><td>{value}</td></tr>\n"
    html += "</table>\n"
    return html


def make_index(runners_info, n_solutions, out_path):
    rows = ""
    for runner, counts_solo, counts_binome, html_name in runners_info:
        counts = counts_solo + counts_binome
        active = int(np.sum(counts > 0))
        always = int(np.sum(counts == n_solutions))
        km_min = int(np.where(counts > 0)[0][0]) * SEGMENT_KM if active else "—"
        km_max = (int(np.where(counts > 0)[0][-1]) + 1) * SEGMENT_KM if active else "—"
        rows += (
            f"  <tr>"
            f"<td><a href='{html_name}'>{runner}</a></td>"
            f"<td>{active}</td>"
            f"<td>{always}</td>"
            f"<td>{km_min}–{km_max} km</td>"
            f"</tr>\n"
        )

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>Synthèse des solutions</title>
  <style>
    {CSS}
    table.summary {{ border-collapse: collapse; width: 100%; }}
    table.summary th, table.summary td {{
        border: 1px solid #ddd; padding: 0.5em 0.8em; }}
    table.summary th {{ background: #eaf4fb; }}
    table.summary tr:hover {{ background: #f0f7ff; }}
  </style>
</head>
<body>
  <h1>Synthèse — {n_solutions} solutions énumérées</h1>

  <h2>Paramètres généraux</h2>
  {_params_html()}

  <h2>Coureurs</h2>
  <p>
    Cliquez sur un coureur pour voir ses contraintes et l'histogramme de présence
    par segment élémentaire. —
    <a href="diversity.html">Diversité par segment →</a> —
    <a href="solo_binome.html">Solo vs binôme par segment →</a>
  </p>
  <table class="summary">
    <thead>
      <tr>
        <th>Coureur</th>
        <th>Segments couverts (≥1 sol.)</th>
        <th>Segments dans toutes les solutions</th>
        <th>Plage km</th>
      </tr>
    </thead>
    <tbody>
{rows}    </tbody>
  </table>
</body>
</html>
"""
    out_path.write_text(html, encoding="utf-8")


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    OUT_DIR.mkdir(exist_ok=True)

    print("Chargement des solutions…")
    solutions = load_solutions()
    n = len(solutions)
    print(f"  {n} solutions chargées.")

    runners = list(RUNNERS_DATA.keys())
    runners_info = []

    for runner in runners:
        print(f"  Traitement : {runner}")
        counts_solo, counts_binome = segment_coverage(solutions, runner)
        img_name = f"{runner.lower()}_histogram.png"
        img_path = OUT_DIR / img_name
        img_relay_name = f"{runner.lower()}_relay_starts.png"
        img_relay_path = OUT_DIR / img_relay_name
        html_name = f"{runner.lower()}.html"
        html_path = OUT_DIR / html_name

        make_histogram(runner, counts_solo, counts_binome, n, img_path)

        relay_counts = relay_start_coverage(solutions, runner)
        make_relay_start_histogram(runner, relay_counts, n, img_relay_path)

        make_runner_page(runner, counts_solo, counts_binome, n, img_name, img_relay_name, html_path)
        runners_info.append((runner, counts_solo, counts_binome, html_name))

    print("  Génération de la page de diversité…")
    diversity = segment_runner_diversity(solutions)
    make_diversity_histogram(diversity, OUT_DIR / "diversity_histogram.png")
    make_diversity_page(diversity, n, "diversity_histogram.png", OUT_DIR / "diversity.html")

    print("  Génération de la page solo vs binôme…")
    sb_solo, sb_binome = segment_solo_binome(solutions)
    make_solo_binome_histogram(sb_solo, sb_binome, OUT_DIR / "solo_binome_histogram.png")
    make_solo_binome_page(sb_solo, sb_binome, n, "solo_binome_histogram.png", OUT_DIR / "solo_binome.html")

    print("  Génération de la page de synthèse…")
    make_index(runners_info, n, OUT_DIR / "index.html")

    print(f"\nTerminé. Ouvrez : {OUT_DIR / 'index.html'}")


if __name__ == "__main__":
    main()
