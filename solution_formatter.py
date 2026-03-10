
from data import (
    N_SEGMENTS,
    REST_NORMAL,
    REST_NIGHT,
    RUNNERS_DATA,
    MATCHING_CONSTRAINTS,
    TOTAL_KM,
    SEGMENT_KM,
    START_HOUR,
    NIGHT_SEGMENTS,
    segment_start_hour,
)

RUNNERS = list(RUNNERS_DATA.keys())
DAY_NAMES = ["Mercredi", "Jeudi", "Vendredi"]


def _parse_relais(solver, start, same_relay, relais_solo, night_relay):
    relais_list = []
    for r in RUNNERS:
        for k, sz in enumerate(RUNNERS_DATA[r].relais):
            s = solver.value(start[r][k])
            partner = None
            for key, bv in same_relay.items():
                if solver.value(bv) == 1:
                    if key[0] == r and key[1] == k:
                        partner = key[2]
                    elif key[2] == r and key[3] == k:
                        partner = key[0]
            relais_list.append(
                {
                    "runner": r,
                    "k": k,
                    "start": s,
                    "end": s + sz,
                    "size": sz,
                    "km": sz * 5,
                    "solo": bool(solver.value(relais_solo[r][k])),
                    "night": bool(solver.value(night_relay[r][k])),
                    "partner": partner,
                }
            )
    relais_list.sort(key=lambda x: (x["start"], x["runner"]))
    return relais_list


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


def _print_recap_coureurs(relais_list, W):
    print(f"\n{'─' * W}")
    print("  RÉCAPITULATIF PAR COUREUR")
    print(f"{'─' * W}")
    for r in RUNNERS:
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
            print(
                f"    {day_name} {hh:02d}h{mm:02d} → {hh_e:02d}h{mm_e:02d}"
                f"  {rel['km']:>2} km  {p}{nuit}"
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


def _print_verifications(solver, start, same_relay, relais_solo, night_relay):
    print("\n--- Vérifications ---")

    coverage = [0] * N_SEGMENTS
    for r in RUNNERS:
        for k, sz in enumerate(RUNNERS_DATA[r].relais):
            for seg in range(solver.value(start[r][k]), solver.value(start[r][k]) + sz):
                coverage[seg] += 1
    gaps = [s for s in range(N_SEGMENTS) if coverage[s] == 0]
    over = [s for s in range(N_SEGMENTS) if coverage[s] > 2]
    print(
        f"Couverture : {'OK' if not gaps and not over else f'ERREUR gaps={gaps} over={over}'}"
    )

    repos_ok = True
    for r in RUNNERS:
        vals = sorted(
            (
                solver.value(start[r][k]),
                solver.value(start[r][k]) + sz,
                solver.value(night_relay[r][k]),
            )
            for k, sz in enumerate(RUNNERS_DATA[r].relais)
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
    for r in RUNNERS:
        if RUNNERS_DATA[r].nuit_max > 1:
            continue
        n = sum(solver.value(night_relay[r][k]) for k in range(len(RUNNERS_DATA[r].relais)))
        if n > 1:
            print(f"  NUIT x{n} : {r}")
            nuit_ok = False
    if nuit_ok:
        print("Nuit ×1  : OK")

    solo_ok = True
    for r in RUNNERS:
        n = sum(solver.value(relais_solo[r][k]) for k in range(len(RUNNERS_DATA[r].relais)))
        if n > 1:
            print(f"  SOLO x{n} : {r}")
            solo_ok = False
    if solo_ok:
        print("Solo ≤ 1 : OK")

    solo_night_ok = True
    for r in RUNNERS:
        for k in range(len(RUNNERS_DATA[r].relais)):
            if solver.value(relais_solo[r][k]) and solver.value(night_relay[r][k]):
                print(f"  SOLO+NUIT : {r} relais {k}")
                solo_night_ok = False
    if solo_night_ok:
        print("Solo≠Nuit : OK")

    for r1, r2 in MATCHING_CONSTRAINTS["pair_at_least_once"]:
        found = any(
            solver.value(bv) == 1
            for key, bv in same_relay.items()
            if (key[0] == r1 and key[2] == r2) or (key[0] == r2 and key[2] == r1)
        )
        if not found:
            print(f"  BINÔME OBLIGATOIRE MANQUANT: {r1}-{r2}")

    for r1, r2 in MATCHING_CONSTRAINTS["pair_at_most_once"]:
        count = sum(
            solver.value(bv)
            for key, bv in same_relay.items()
            if (key[0] == r1 and key[2] == r2) or (key[0] == r2 and key[2] == r1)
        )
        if count > 1:
            print(f"  BINÔME EN TROP: {r1}-{r2} ({count} relais ensemble)")


def print_solution(solver, start, same_relay, relais_solo, night_relay):
    relais_list = _parse_relais(solver, start, same_relay, relais_solo, night_relay)
    W = 74
    _print_planning_chrono(relais_list, W)
    _print_recap_coureurs(relais_list, W)
    _print_stats(relais_list, W)
    _print_verifications(solver, start, same_relay, relais_solo, night_relay)


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


def formatte_html(solver, start, same_relay, relais_solo, night_relay):
    relais_list = _parse_relais(solver, start, same_relay, relais_solo, night_relay)

    by_runner = {r: {} for r in RUNNERS}
    for rel in relais_list:
        by_runner[rel["runner"]][rel["start"]] = rel

    def unavail_segs(runner):
        if not RUNNERS_DATA[runner].dispo:
            return set()
        avail = set()
        for s, e in RUNNERS_DATA[runner].dispo:
            avail.update(range(s, e))
        return set(range(N_SEGMENTS)) - avail

    # Segments les plus proches des heures marquées (0h, 6h, 12h, 18h)
    # On casse les spans à ces frontières pour pouvoir y placer un border-left
    SEG_WIDTH_PX = 10
    mark_segs = set()
    for day in range(4):
        for hh_mark in (0, 6, 12, 18):
            target_h = day * 24 + hh_mark
            best = min(range(N_SEGMENTS + 1), key=lambda s: abs(segment_start_hour(s) - target_h))
            if 0 < best <= N_SEGMENTS:
                mark_segs.add(best)

    def split_spans(spans):
        """Coupe les spans aux frontières mark_segs."""
        result = []
        for s, e, typ, label in spans:
            cuts = sorted(m for m in mark_segs if s < m < e)
            boundaries = [s] + cuts + [e]
            for i in range(len(boundaries) - 1):
                result.append((boundaries[i], boundaries[i + 1], typ, label if i == 0 else ""))
        return result

    rows_html = []
    for r in sorted(RUNNERS):
        unavail = unavail_segs(r)
        relais_by_start = by_runner[r]
        sorted_relais = sorted(relais_by_start.values(), key=lambda x: x["start"])

        # Segments de repos-post-nuit : [fin_relais_nuit, fin_relais_nuit + REST_NIGHT)
        post_night_segs = set()
        for rel in sorted_relais:
            if rel["night"]:
                post_night_segs.update(range(rel["end"], rel["end"] + REST_NIGHT))

        spans = []
        seg = 0
        while seg < N_SEGMENTS:
            if seg in relais_by_start:
                rel = relais_by_start[seg]
                relay_typ = "relay_solo" if rel["solo"] else ("relay_binome" if rel["partner"] else "relay_solo")
                spans.append((seg, rel["end"], relay_typ, ""))
                seg = rel["end"]
            elif seg in unavail:
                end = seg + 1
                while end < N_SEGMENTS and end in unavail and end not in relais_by_start:
                    end += 1
                spans.append((seg, end, "unavail", ""))
                seg = end
            else:
                next_event = N_SEGMENTS
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
                is_night = all(seg_i in NIGHT_SEGMENTS for seg_i in range(s, e))
                is_post_night = any(seg_i in post_night_segs for seg_i in range(s, e))
                bg = "#d0d0d0" if (is_night or is_post_night) else "#ffffff"
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
    for seg in range(N_SEGMENTS):
        h = segment_start_hour(seg)
        day = int(h // 24)
        hh = int(h) % 24
        mm = int((h % 1) * 60)
        is_mark = seg in mark_segs
        # Heure cible la plus proche pour ce mark_seg
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

    h_end = segment_start_hour(N_SEGMENTS)
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
<h2>Planning {TOTAL_KM} km — {N_SEGMENTS} segments de {SEGMENT_KM} km</h2>
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
{_html_text_sections(relais_list)}
</body>
</html>"""
    return html


def _html_text_sections(relais_list):
    import io
    import sys

    W = 74
    buf = io.StringIO()
    old_stdout, sys.stdout = sys.stdout, buf
    _print_planning_chrono(relais_list, W)
    _print_recap_coureurs(relais_list, W)
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


def save_solution(solver, start, same_relay, relais_solo, night_relay):
    """Affiche la solution et la sauvegarde dans un fichier horodaté.

    Thread-safe : protège la redirection de sys.stdout par un verrou global
    et utilise un compteur atomique pour éviter les collisions de noms de fichiers
    quand plusieurs solutions arrivent dans la même seconde.
    """
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
        print_solution(solver, start, same_relay, relais_solo, night_relay)
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

        relais_list = _parse_relais(solver, start, same_relay, relais_solo, night_relay)
        csv_fname = os.path.join(outdir, f"planning_{suffix}.csv")
        _save_csv(relais_list, csv_fname)
        print(f"CSV sauvegardé      : {csv_fname}")

        html_fname = os.path.join(outdir, f"planning_{suffix}.html")
        with open(html_fname, "w", encoding="utf-8") as f:
            f.write(formatte_html(solver, start, same_relay, relais_solo, night_relay))
        print(f"HTML sauvegardé     : {html_fname}")
