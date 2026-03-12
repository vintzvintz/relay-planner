"""
Formatage des solutions CP-SAT.

Fonctions publiques utilisées par enumerate_optimal_solutions.py :
  _save_csv(relais_list, csv_path)

Fonctions internes utilisées par RelayModel :
  _print_solution_impl(relay_model)
  _formatte_html_impl(relay_model) -> str
  _save_solution_impl(relay_model)
"""

from data import (
    N_SEGMENTS,
    REST_NORMAL,
    REST_NIGHT,
    TOTAL_KM,
    SEGMENT_KM,
    START_HOUR,
    NIGHT_SEGMENTS,
    segment_start_hour,
)

DAY_NAMES = ["Mercredi", "Jeudi", "Vendredi"]



def _fmt(seg):
    h = segment_start_hour(seg)
    day, hh, mm = int(h // 24), int(h) % 24, int((h % 1) * 60)
    return DAY_NAMES[min(day, 2)], hh, mm


def _print_planning_chrono(relais_list, W):
    h_end = segment_start_hour(N_SEGMENTS)
    day_end = DAY_NAMES[min(int(h_end // 24), 2)]
    hh_end, mm_end = int(h_end) % 24, int((h_end % 1) * 60)
    print("=" * W)
    print(f"  PLANNING  {TOTAL_KM} km — {N_SEGMENTS} segments de {SEGMENT_KM} km")
    print(
        f"  Départ : {DAY_NAMES[0]} {START_HOUR:02d}h00"
        f"          Arrivée : {day_end} ~{hh_end:02d}h{mm_end:02d}"
    )
    print("=" * W)

    current_day = -1
    seen = set()
    for rel in relais_list:
        _, hh, mm = _fmt(rel["start"])
        day = int(segment_start_hour(rel["start"]) // 24)

        if day != current_day:
            current_day = day
            print(f"\n  ▶ {DAY_NAMES[min(day, 2)].upper()}")

        dedup = (
            min(rel["runner"], rel["partner"] or "zzz"),
            max(rel["runner"], rel["partner"] or "zzz"),
            rel["start"],
        )
        if dedup in seen and rel["partner"]:
            continue
        seen.add(dedup)

        _, hh_end, mm_end = _fmt(rel["end"])
        debut = f"{DAY_NAMES[min(day, 2)]} {hh:02d}h{mm:02d}"
        fin = f"{hh_end:02d}h{mm_end:02d}"
        dist = f"{rel['start'] * 5}–{rel['end'] * 5} km"
        coureurs = f"{rel['runner']} + {rel['partner']}" if rel["partner"] else f"{rel['runner']}  (seul)"
        nuit = "  [nuit]" if rel["night"] else ""
        print(f"  {debut} → {fin}   {dist:<14}  {rel['km']:>2} km   {coureurs}{nuit}")


def _print_recap_coureurs(relais_list, W, runners):
    print(f"\n{'─' * W}")
    print("  RÉCAPITULATIF PAR COUREUR")
    print(f"{'─' * W}")
    for r in runners:
        r_rels = sorted(
            [x for x in relais_list if x["runner"] == r], key=lambda x: x["start"]
        )
        total = sum(x["km"] for x in r_rels)
        n_solo = sum(1 for x in r_rels if x["solo"])
        n_nuit = sum(1 for x in r_rels if x["night"])
        flags = []
        if n_solo:
            flags.append(f"{n_solo} seul")
        if n_nuit:
            flags.append(f"{n_nuit} nuit")
        print(
            f"\n  {r:<12}  {total:>3} km  {len(r_rels)} relais"
            + (f"  ({', '.join(flags)})" if flags else "")
        )
        for i, rel in enumerate(r_rels):
            day_name, hh, mm = _fmt(rel["start"])
            _, hh_e, mm_e = _fmt(rel["end"])
            p = f"avec {rel['partner']}" if rel["partner"] else "seul"
            nuit = " [nuit]" if rel["night"] else ""
            flex = " [flex]" if rel["flex"] else ""
            print(
                f"    {day_name} {hh:02d}h{mm:02d} → {hh_e:02d}h{mm_e:02d}"
                f"  {rel['km']:>2} km  {p}{nuit}{flex}"
            )
            if i < len(r_rels) - 1:
                rest_h = segment_start_hour(r_rels[i + 1]["start"]) - segment_start_hour(rel["end"])
                rh, rm = int(rest_h), int((rest_h % 1) * 60)
                print(f"    Repos {rh}h{rm:02d}")


def _print_stats(relais_list, W):
    n_binomes = sum(1 for x in relais_list if x["partner"]) // 2
    solos = [x for x in relais_list if x["solo"]]
    n_solos = len(solos)
    km_solos = sum(x["km"] for x in solos)
    print(f"\n{'─' * W}")
    print(
        f"  Binômes : {n_binomes}   Solos : {n_solos} ({km_solos} km)   "
        f"Total relais : {len(relais_list)}"
    )
    print("=" * W)


def _print_verifications(relay_model, solver):
    print("\n--- Vérifications ---")
    c = relay_model.constraints
    runners = relay_model.runners

    coverage = [0] * c.n_segments
    for r in runners:
        for k in range(len(c.runners_data[r].relais)):
            sz = solver.value(relay_model.size[r][k])
            for seg in range(solver.value(relay_model.start[r][k]), solver.value(relay_model.start[r][k]) + sz):
                coverage[seg] += 1
    gaps = [s for s in range(c.n_segments) if coverage[s] == 0]
    over = [s for s in range(c.n_segments) if coverage[s] > 2]
    print(
        f"Couverture : {'OK' if not gaps and not over else f'ERREUR gaps={gaps} over={over}'}"
    )

    repos_ok = True
    for r in runners:
        vals = sorted(
            (
                solver.value(relay_model.start[r][k]),
                solver.value(relay_model.start[r][k]) + solver.value(relay_model.size[r][k]),
                solver.value(relay_model.night_relay[r][k]),
            )
            for k in range(len(c.runners_data[r].relais))
        )
        for i in range(len(vals) - 1):
            _, e_prev, night_prev = vals[i]
            s_next, _, _ = vals[i + 1]
            required = REST_NIGHT if night_prev else REST_NORMAL
            if s_next - e_prev < required:
                print(f"  REPOS {r}: gap={s_next - e_prev} < {required}")
                repos_ok = False
    if repos_ok:
        print("Repos    : OK")

    nuit_ok = True
    for r in runners:
        if c.runners_data[r].nuit_max > 1:
            continue
        n = sum(solver.value(relay_model.night_relay[r][k]) for k in range(len(c.runners_data[r].relais)))
        if n > 1:
            print(f"  NUIT x{n} : {r}")
            nuit_ok = False
    if nuit_ok:
        print("Nuit ×1  : OK")

    solo_ok = True
    for r in runners:
        n = sum(solver.value(relay_model.relais_solo[r][k]) for k in range(len(c.runners_data[r].relais)))
        if n > 1:
            print(f"  SOLO x{n} : {r}")
            solo_ok = False
    if solo_ok:
        print("Solo ≤ 1 : OK")

    solo_night_ok = True
    for r in runners:
        for k in range(len(c.runners_data[r].relais)):
            if solver.value(relay_model.relais_solo[r][k]) and solver.value(relay_model.night_relay[r][k]):
                print(f"  SOLO+NUIT : {r} relais {k}")
                solo_night_ok = False
    if solo_night_ok:
        print("Solo≠Nuit : OK")

    for r1, r2 in c.matching_constraints["pair_at_least_once"]:
        found = any(
            solver.value(bv) == 1
            for key, bv in relay_model.same_relay.items()
            if (key[0] == r1 and key[2] == r2) or (key[0] == r2 and key[2] == r1)
        )
        if not found:
            print(f"  BINÔME OBLIGATOIRE MANQUANT: {r1}-{r2}")

    for r1, r2 in c.matching_constraints["pair_at_most_once"]:
        count = sum(
            solver.value(bv)
            for key, bv in relay_model.same_relay.items()
            if (key[0] == r1 and key[2] == r2) or (key[0] == r2 and key[2] == r1)
        )
        if count > 1:
            print(f"  BINÔME EN TROP: {r1}-{r2} ({count} relais ensemble)")


def _print_solution_impl(relay_model):
    relais_list = relay_model.parse_relais()
    W = 74
    _print_planning_chrono(relais_list, W)
    _print_recap_coureurs(relais_list, W, relay_model.runners)
    _print_stats(relais_list, W)
    _print_verifications(relay_model, relay_model.solver)


def _save_csv(relais_list, csv_path):
    import csv

    rows = []
    for rel in relais_list:
        day_name, hh, mm = _fmt(rel["start"])
        _, hh_e, mm_e = _fmt(rel["end"])
        rows.append({
            "jour": day_name,
            "debut": f"{hh:02d}:{mm:02d}",
            "fin": f"{hh_e:02d}:{mm_e:02d}",
            "km_debut": rel["start"] * 5,
            "km_fin": rel["end"] * 5,
            "distance_km": rel["km"],
            "coureur": rel["runner"],
            "partenaire": rel["partner"] or "",
            "solo": "oui" if rel["solo"] else "non",
            "nuit": "oui" if rel["night"] else "non",
        })

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def _formatte_html_impl(relay_model):
    relais_list = relay_model.parse_relais()
    c = relay_model.constraints
    runners = relay_model.runners

    by_runner = {r: {} for r in runners}
    for rel in relais_list:
        by_runner[rel["runner"]][rel["start"]] = rel

    def unavail_segs(runner):
        if not c.runners_data[runner].dispo:
            return set()
        avail = set()
        for s, e in c.runners_data[runner].dispo:
            avail.update(range(s, e))
        return set(range(c.n_segments)) - avail

    SEG_WIDTH_PX = 10
    mark_segs = set()
    for day in range(4):
        for hh_mark in (0, 6, 12, 18):
            target_h = day * 24 + hh_mark
            best = min(range(c.n_segments + 1), key=lambda s: abs(segment_start_hour(s) - target_h))
            if 0 < best <= c.n_segments:
                mark_segs.add(best)

    def split_spans(spans):
        result = []
        for s, e, typ, label in spans:
            cuts = sorted(m for m in mark_segs if s < m < e)
            boundaries = [s] + cuts + [e]
            for i in range(len(boundaries) - 1):
                result.append((boundaries[i], boundaries[i + 1], typ, label if i == 0 else ""))
        return result

    rows_html = []
    for r in sorted(runners):
        unavail = unavail_segs(r)
        relais_by_start = by_runner[r]
        sorted_relais = sorted(relais_by_start.values(), key=lambda x: x["start"])

        post_night_segs = set()
        for rel in sorted_relais:
            if rel["night"]:
                post_night_segs.update(range(rel["end"], rel["end"] + REST_NIGHT))

        spans = []
        seg = 0
        while seg < c.n_segments:
            if seg in relais_by_start:
                rel = relais_by_start[seg]
                relay_typ = "relay_solo" if rel["solo"] else ("relay_binome" if rel["partner"] else "relay_solo")
                spans.append((seg, rel["end"], relay_typ, ""))
                seg = rel["end"]
            elif seg in unavail:
                end = seg + 1
                while end < c.n_segments and end in unavail and end not in relais_by_start:
                    end += 1
                spans.append((seg, end, "unavail", ""))
                seg = end
            else:
                next_event = c.n_segments
                for rs in sorted_relais:
                    if rs["start"] > seg:
                        next_event = min(next_event, rs["start"])
                        break
                for us in sorted(unavail):
                    if us > seg:
                        next_event = min(next_event, us)
                        break
                end = next_event
                n_segs = end - seg
                h = n_segs * (SEGMENT_KM / 9)
                hh, mm = int(h), int((h % 1) * 60)
                label = f"{hh}h{mm:02d}" if n_segs > 0 else ""
                spans.append((seg, end, "free", label))
                seg = end

        spans = split_spans(spans)

        tds = []
        for s, e, typ, label in spans:
            colspan = e - s
            if colspan == 0:
                continue
            bl = "border-left:2px solid #000;" if s in mark_segs else ""
            if typ == "free":
                is_night_span = all(seg_i in NIGHT_SEGMENTS for seg_i in range(s, e))
                is_post_night = any(seg_i in post_night_segs for seg_i in range(s, e))
                bg = "#d0d0d0" if (is_night_span or is_post_night) else "#ffffff"
                style = f"background:{bg};color:#555;font-size:10px;text-align:center;border:1px solid #ccc;{bl}"
            elif typ == "relay_binome":
                style = f"background:#4caf50;color:#000;font-size:10px;text-align:center;font-weight:bold;border:1px solid #2e7d32;{bl}"
            elif typ == "relay_solo":
                style = f"background:#f48fb1;color:#000;font-size:10px;text-align:center;font-weight:bold;border:1px solid #c2185b;{bl}"
            elif typ == "unavail":
                style = f"background:#8b00ff;border:1px solid #6a00cc;{bl}"
            else:
                style = f"background:#fff;border:1px solid #ccc;{bl}"
            tds.append(f'<td colspan="{colspan}" style="{style}">{label}</td>')

        row = (
            f'<tr><th style="text-align:left;padding:2px 6px;white-space:nowrap;'
            f'font-size:12px;">{r}</th>{"".join(tds)}</tr>'
        )
        rows_html.append(row)

    header_tds = ['<th style="padding:1px;font-size:9px;width:20px;min-width:20px;"></th>']
    prev_day = -1
    for seg in range(c.n_segments):
        h = segment_start_hour(seg)
        day = int(h // 24)
        is_mark = seg in mark_segs
        if is_mark:
            h_mod = h % 24
            closest_hh = min((0, 6, 12, 18), key=lambda hm: min(abs(h_mod - hm), 24 - abs(h_mod - hm)))
            label = f"{closest_hh:02d}h"
        else:
            label = ""
        bg = "#333" if day != prev_day else "#555"
        prev_day = day
        bl = "border-left:2px solid #fff;" if is_mark else ""
        header_tds.append(
            f'<th style="background:{bg};color:#fff;font-size:8px;padding:1px;'
            f'text-align:center;width:{SEG_WIDTH_PX}px;min-width:{SEG_WIDTH_PX}px;{bl}">{label}</th>'
        )
    header_row = f'<tr>{"".join(header_tds)}</tr>'

    h_end = segment_start_hour(c.n_segments)
    day_end = DAY_NAMES[min(int(h_end // 24), 2)]
    hh_end, mm_end = int(h_end) % 24, int((h_end % 1) * 60)

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Planning {TOTAL_KM} km</title>
<style>
  body {{ font-family: sans-serif; font-size: 12px; margin: 16px; }}
  table {{ border-collapse: collapse; table-layout: fixed; }}
  th, td {{ padding: 2px; }}
</style>
</head>
<body>
<h2>Planning {TOTAL_KM} km — {c.n_segments} segments de {SEGMENT_KM} km</h2>
<p>Départ : {DAY_NAMES[0]} {START_HOUR:02d}h00 &nbsp;|&nbsp; Arrivée : {day_end} ~{hh_end:02d}h{mm_end:02d}</p>
<p>
  <span style="background:#4caf50;padding:2px 8px;border:1px solid #2e7d32;">Relais binôme</span>&nbsp;
  <span style="background:#f48fb1;padding:2px 8px;border:1px solid #c2185b;">Relais solo</span>&nbsp;
  <span style="background:#ffffff;border:1px solid #ccc;padding:2px 8px;">Repos (jour)</span>&nbsp;
  <span style="background:#d0d0d0;border:1px solid #ccc;padding:2px 8px;">Repos (nuit)</span>&nbsp;
  <span style="background:#8b00ff;padding:2px 8px;border:1px solid #6a00cc;">&nbsp;&nbsp;&nbsp;</span> Indisponible
</p>
<div style="overflow-x:auto;">
<table>
{header_row}
{"".join(rows_html)}
</table>
</div>
{_html_text_sections(relais_list, relay_model.runners)}
</body>
</html>"""
    return html


def _html_text_sections(relais_list, runners):
    import io
    import sys

    W = 74
    buf = io.StringIO()
    old_stdout, sys.stdout = sys.stdout, buf
    _print_planning_chrono(relais_list, W)
    _print_recap_coureurs(relais_list, W, runners)
    sys.stdout = old_stdout
    text = buf.getvalue()

    return (
        '<h3 style="margin-top:2em;">Planning détaillé</h3>'
        '<pre style="font-family:monospace;font-size:12px;'
        'background:#f8f8f8;border:1px solid #ddd;padding:12px;'
        'overflow-x:auto;white-space:pre;">'
        + text
        + "</pre>"
    )


_save_lock = __import__("threading").Lock()
_save_counter = 0


def _save_solution_impl(relay_model):
    """Affiche la solution et la sauvegarde dans des fichiers horodatés."""
    import io
    import sys
    import os
    from datetime import datetime

    global _save_counter

    with _save_lock:
        _save_counter += 1
        seq = _save_counter

        buf = io.StringIO()
        old_stdout, sys.stdout = sys.stdout, buf
        _print_solution_impl(relay_model)
        sys.stdout = old_stdout
        output = buf.getvalue()
        print(output)

        outdir = "plannings"
        os.makedirs(outdir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"{ts}_{seq:03d}"

        fname = os.path.join(outdir, f"planning_{suffix}.txt")
        with open(fname, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Planning sauvegardé : {fname}")

        relais_list = relay_model.parse_relais()
        csv_fname = os.path.join(outdir, f"planning_{suffix}.csv")
        _save_csv(relais_list, csv_fname)
        print(f"CSV sauvegardé      : {csv_fname}")

        html_fname = os.path.join(outdir, f"planning_{suffix}.html")
        with open(html_fname, "w", encoding="utf-8") as f:
            f.write(_formatte_html_impl(relay_model))
        print(f"HTML sauvegardé     : {html_fname}")
