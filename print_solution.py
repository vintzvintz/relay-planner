
from data import (
    N_SEGMENTS,
    REST_NORMAL,
    REST_NIGHT,
    RUNNER_RELAYS,
    MANDATORY_PAIRS,
    MULTI_NIGHT_ALLOWED,
    TOTAL_KM,
    SEGMENT_KM,
    START_HOUR,
    segment_start_hour,
)

RUNNERS = list(RUNNER_RELAYS.keys())
DAY_NAMES = ["Mercredi", "Jeudi", "Vendredi"]


def _parse_relais(solver, start, same_relay, relais_solo, night_relay):
    relais_list = []
    for r in RUNNERS:
        for k, sz in enumerate(RUNNER_RELAYS[r]):
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
        for rel in r_rels:
            day_name, hh, mm = _fmt(rel["start"])
            _, hh_e, mm_e = _fmt(rel["end"])
            p = f"avec {rel['partner']}" if rel["partner"] else "seul"
            nuit = " [nuit]" if rel["night"] else ""
            print(
                f"    {day_name} {hh:02d}h{mm:02d} → {hh_e:02d}h{mm_e:02d}"
                f"  {rel['km']:>2} km  {p}{nuit}"
            )


def _print_stats(relais_list, W):
    n_binomes = sum(1 for x in relais_list if x["partner"]) // 2
    n_solos = sum(1 for x in relais_list if x["solo"])
    print(f"\n{'─' * W}")
    print(
        f"  Binômes : {n_binomes}   Solos : {n_solos}   "
        f"Total relais : {len(relais_list)}"
    )
    print("=" * W)


def _print_verifications(solver, start, same_relay, relais_solo, night_relay):
    print("\n--- Vérifications ---")

    coverage = [0] * N_SEGMENTS
    for r in RUNNERS:
        for k, sz in enumerate(RUNNER_RELAYS[r]):
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
            for k, sz in enumerate(RUNNER_RELAYS[r])
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
        if r in MULTI_NIGHT_ALLOWED:
            continue
        n = sum(solver.value(night_relay[r][k]) for k in range(len(RUNNER_RELAYS[r])))
        if n > 1:
            print(f"  NUIT x{n} : {r}")
            nuit_ok = False
    if nuit_ok:
        print("Nuit ×1  : OK")

    solo_ok = True
    for r in RUNNERS:
        n = sum(solver.value(relais_solo[r][k]) for k in range(len(RUNNER_RELAYS[r])))
        if n > 1:
            print(f"  SOLO x{n} : {r}")
            solo_ok = False
    if solo_ok:
        print("Solo ≤ 1 : OK")

    solo_night_ok = True
    for r in RUNNERS:
        for k in range(len(RUNNER_RELAYS[r])):
            if solver.value(relais_solo[r][k]) and solver.value(night_relay[r][k]):
                print(f"  SOLO+NUIT : {r} relais {k}")
                solo_night_ok = False
    if solo_night_ok:
        print("Solo≠Nuit : OK")

    for r1, r2 in MANDATORY_PAIRS:
        found = any(
            solver.value(bv) == 1
            for key, bv in same_relay.items()
            if (key[0] == r1 and key[2] == r2) or (key[0] == r2 and key[2] == r1)
        )
        if not found:
            print(f"  BINÔME OBLIGATOIRE MANQUANT: {r1}-{r2}")


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


def save_solution(solver, start, same_relay, relais_solo, night_relay):
    """Affiche la solution et la sauvegarde dans un fichier horodaté."""
    import io
    import sys
    import os
    from datetime import datetime

    buf = io.StringIO()
    old_stdout, sys.stdout = sys.stdout, buf
    print_solution(solver, start, same_relay, relais_solo, night_relay)
    sys.stdout = old_stdout
    output = buf.getvalue()
    print(output)

    outdir = "plannings"
    os.makedirs(outdir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    fname = os.path.join(outdir, f"planning_{ts}.txt")
    with open(fname, "w") as f:
        f.write(output)
    print(f"Planning sauvegardé : {fname}")

    relais_list = _parse_relais(solver, start, same_relay, relais_solo, night_relay)
    csv_fname = os.path.join(outdir, f"planning_{ts}.csv")
    _save_csv(relais_list, csv_fname)
    print(f"CSV sauvegardé      : {csv_fname}")
