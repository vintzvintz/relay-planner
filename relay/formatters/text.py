# TODO : add module docstring

# ------------------------------------------------------------------
# Rendu texte
# ------------------------------------------------------------------

from .commun import summary_data, build_chrono_entries, build_runner_recaps

from .commun import _fmt_deniv


PLANNING_WIDTH = 85
DENIV_WIDTH = 6  # signe + 4 chiffres max + 'm'

def _max_label_width(relays, label_fn) -> int:
    return max((len(label_fn(r)) for r in relays), default=0)


def _text_lb_solos_str(d: dict) -> str:
    if d["lb_solos"] is None:
        return ""
    return f" ≥{d['lb_solos']}"


def _build_text_summary(solution) -> list[str]:
    c = solution.constraints
    d = summary_data(solution)
    ub_parts = []
    if d["ub_score_target"] is not None:
        ub_parts.append(f"≤{d['ub_score_target']} (target)")
    ub_str = f"  majorant {' / '.join(ub_parts)}" if ub_parts else ""
    return [
        "=" * PLANNING_WIDTH,
        f"  Planning {c.total_km:.1f} km     {d['day_start']} {d['hh_start']:02d}h{d['mm_start']:02d} -> {d['day_end']} {d['hh_end']:02d}h{d['mm_end']:02d}",
        f"  {d['nb_coureurs']} coureurs - {d['km_engages']:.1f} km engagés - {d['nb_points']} points - {d['min_per_km_str']} min/km",
        f"  score {d['score_str']}{ub_str} - {d['n_solos']} solos ({d['km_solo']:.1f} km){_text_lb_solos_str(d)} - flex +{d['flex_plus_str']} / -{d['flex_moins_str']} km",
        "=" * PLANNING_WIDTH,
    ]


def _build_text_chrono(solution):
    c = solution.constraints
    relays = solution.relays
    lines = []

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
        total_flex_str = f"({recap.total_flex:+.1f})"
        lines.append(
            f"\n{recap.name:<{RECAP_TITLE_WIDTH}}   {recap.total_km:>4.1f} km"
            f"  {total_flex_str:>8}"
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
                f"  {rl.flex_str:>8}"
                f"   {rl.partenaire:<{pw}}{dplus_str}  {rl.repos_str:<11}{flags_rel}"
            )

    return lines


def to_text(solution) -> str:
    """Retourne le planning complet en texte (planning chrono + récap)."""
    lines = _build_text_summary(solution) + _build_text_chrono(solution) + _build_text_recap(solution)
    return "\n".join(lines) + "\n"

