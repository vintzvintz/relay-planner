"""
relay/verifications.py

Vérifications post-résolution pour le modèle waypoint.
Portage de relay/verifications.py, adapté aux points de passage :
  - start/end sont des indices de points (pas de segments)
  - les arcs couverts par un relais sont [start, start+1, ..., end-1]
  - pause_arcs : ensemble d'indices d'arcs à exclure de la couverture
  - temps en minutes via cumul_temps
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .constraints import Constraints


def check(solution) -> bool:
    """Vérifie la cohérence de la solution courante. solution est une Solution."""
    relays = solution.relays
    constraints = solution.constraints

    import io
    out = io.StringIO()

    print("\n--- Vérifications ---", file=out)

    if not _check_unknown_runners(relays, constraints, out):
        return False, out

    if not _check_start_end_order(relays, constraints, out):
        return False, out

    ok = True
    ok &= _check_derived_fields(relays, constraints, out)
    ok &= _check_coverage(relays, constraints, out)
    ok &= _check_pauses(relays, constraints, out)
    ok &= _check_relay_sizes(relays, constraints, out)
    ok &= _check_rest(relays, constraints, out)
    ok &= _check_night_max(relays, constraints, out)
    ok &= _check_solo_max(relays, constraints, out)
    ok &= _check_solo_intervals(relays, constraints, out)
    ok &= _check_no_overlap_between_runners(relays, out)
    ok &= _check_pairings(relays, constraints, out)
    ok &= _check_compatibility_matrix(relays, constraints, out)
    ok &= _check_max_duos(relays, constraints, out)
    ok &= _check_max_same_partenaire(relays, constraints, out)
    ok &= _check_solo(relays, constraints, out)
    ok &= _check_chained(relays, constraints, out)
    ok &= _check_availability(relays, constraints, out)
    ok &= _check_pinned(relays, constraints, out)
    ok &= _check_dplus_max(relays, constraints, out)
    ok &= _check_night_vs_time(relays, constraints, out)
    ok &= _check_solo_vs_partner(relays, out)
    ok &= _check_partner_reciprocity(relays, out)
    ok &= _check_km_consistency(relays, out)

    return ok, out


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _build_internal_to_user_map(constraints: "Constraints") -> dict[int, int]:
    """Construit le mapping index interne → index utilisateur.

    Même logique que Solution.from_cpsat() :
    Un point fictif (arc+1) partage l'index utilisateur du point réel suivant.
    """
    pause_point_indices = {arc + 1 for arc in constraints.pause_arcs}
    internal_to_user: dict[int, int] = {}
    user_idx = 0
    for i in range(constraints.nb_points):
        if i in pause_point_indices:
            internal_to_user[i] = user_idx - 1  # même index que le point réel précédent
        else:
            internal_to_user[i] = user_idx
            user_idx += 1
    return internal_to_user


def _relais_by_runner(relays: list[dict]) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for rel in relays:
        result.setdefault(rel["runner"], []).append(rel)
    return result


def _active_pairs(relays: list[dict]) -> list[tuple[str, str]]:
    pairs = []
    seen: set[frozenset] = set()
    for rel in relays:
        if rel["partner"] is not None:
            key = frozenset({rel["runner"], rel["partner"]})
            if key not in seen:
                seen.add(key)
                pairs.append((rel["runner"], rel["partner"]))
    return pairs


def _check_derived_fields(relays: list[dict], constraints: "Constraints", out) -> bool:
    """Vérifie que les champs calculés correspondent aux indices internes.

    Contrôle la cohérence entre :
    - start/end (indices internes) et km_start/km_end (via waypoints_km)
    - start/end et km (distance via cumul_m)
    - start/end et time_start_min/time_end_min (via cumul_temps)
    - start/end et wp_start/wp_end (via internal_to_user)
    - start/end et lat/lon/alt (via waypoints)
    """
    ok = True
    internal_to_user = _build_internal_to_user_map(constraints)

    TOL_KM = 0.01   # 10 m
    TOL_MIN = 0.5   # 30 s

    for rel in relays:
        r, k = rel["runner"], rel["k"]
        s, e = rel["start"], rel["end"]

        # km_start / km_end
        expected_km_start = constraints.waypoints_km[s]
        expected_km_end = constraints.waypoints_km[e]
        if "km_start" in rel and abs(rel["km_start"] - expected_km_start) > TOL_KM:
            print(
                f"  CHAMP {r}[{k}]: km_start={rel['km_start']:.3f}"
                f" attendu {expected_km_start:.3f}",
                file=out,
            )
            ok = False
        if "km_end" in rel and abs(rel["km_end"] - expected_km_end) > TOL_KM:
            print(
                f"  CHAMP {r}[{k}]: km_end={rel['km_end']:.3f}"
                f" attendu {expected_km_end:.3f}",
                file=out,
            )
            ok = False

        # km (distance)
        expected_km = (constraints.cumul_m[e] - constraints.cumul_m[s]) / 1000.0
        if abs(rel["km"] - expected_km) > TOL_KM:
            print(
                f"  CHAMP {r}[{k}]: km={rel['km']:.3f}"
                f" attendu {expected_km:.3f}",
                file=out,
            )
            ok = False

        # time_start_min / time_end_min
        expected_ts = constraints.cumul_temps[s]
        expected_te = constraints.cumul_temps[e]
        if abs(rel["time_start_min"] - expected_ts) > TOL_MIN:
            print(
                f"  CHAMP {r}[{k}]: time_start_min={rel['time_start_min']:.1f}"
                f" attendu {expected_ts}",
                file=out,
            )
            ok = False
        if abs(rel["time_end_min"] - expected_te) > TOL_MIN:
            print(
                f"  CHAMP {r}[{k}]: time_end_min={rel['time_end_min']:.1f}"
                f" attendu {expected_te}",
                file=out,
            )
            ok = False

        # wp_start / wp_end (optionnels)
        if "wp_start" in rel and rel["wp_start"] != internal_to_user[s]:
            print(
                f"  CHAMP {r}[{k}]: wp_start={rel['wp_start']}"
                f" attendu {internal_to_user[s]}",
                file=out,
            )
            ok = False
        if "wp_end" in rel and rel["wp_end"] != internal_to_user[e]:
            print(
                f"  CHAMP {r}[{k}]: wp_end={rel['wp_end']}"
                f" attendu {internal_to_user[e]}",
                file=out,
            )
            ok = False

        # lat/lon/alt (optionnel, seulement si présent ET que source a la clé)
        for side, pt in (("start", s), ("end", e)):
            wp = constraints.waypoints[pt]
            for field in ("lat", "lon", "alt"):
                key = f"{field}_{side}"
                if key in rel and rel[key] is not None and field in wp:
                    if abs(rel[key] - wp[field]) > 1e-6:
                        print(
                            f"  CHAMP {r}[{k}]: {key}={rel[key]}"
                            f" attendu {wp[field]}",
                            file=out,
                        )
                        ok = False

    if ok:
        print("Champs dérivés : OK", file=out)
    return ok


# ------------------------------------------------------------------
# Vérifications
# ------------------------------------------------------------------

def _check_unknown_runners(relays: list[dict], constraints: "Constraints", out) -> bool:
    unknown = {rel["runner"] for rel in relays if rel["runner"] not in constraints.runners_data}
    if unknown:
        for r in sorted(unknown):
            print(f"  COUREUR INCONNU : {r} (absent des contraintes courantes)", file=out)
        return False
    return True


def _check_coverage(relays: list[dict], constraints: "Constraints", out) -> bool:
    """Vérifie que chaque arc (hors pauses) est couvert 1 ou 2 fois."""
    coverage = [0] * constraints.nb_arcs
    for rel in relays:
        for arc in range(rel["start"], rel["end"]):
            coverage[arc] += 1
    active = [a for a in range(constraints.nb_arcs) if a not in constraints.pause_arcs]
    gaps = [a for a in active if coverage[a] == 0]
    over = [a for a in range(constraints.nb_arcs) if coverage[a] > 2]
    ok = not gaps and not over
    print(
        f"Couverture     : {'OK' if ok else f'ERREUR gaps={gaps} over={over}'}",
        file=out,
    )
    return ok


def _check_pauses(relays: list[dict], constraints: "Constraints", out) -> bool:
    """Vérifie qu'aucun relais ne traverse un arc de pause."""
    ok = True
    for rel in relays:
        for arc in range(rel["start"], rel["end"]):
            if arc in constraints.pause_arcs:
                print(
                    f"  PAUSE FRANCHIE : {rel['runner']}[{rel['k']}]"
                    f"=[{rel['start']},{rel['end']}[ couvre l'arc pause {arc}",
                    file=out,
                )
                ok = False
                break
    if ok:
        print("Pauses         : OK", file=out)
    return ok


def _check_relay_sizes(relays: list[dict], constraints: "Constraints", out) -> bool:
    """Vérifie que la distance de chaque relais respecte min_m/max_m."""
    ok = True
    for rel in relays:
        r, k = rel["runner"], rel["k"]
        spec = constraints.runners_data[r].relais[k]
        dist_m = round(rel["km"] * 1000)
        if spec.min_m is not None and dist_m < spec.min_m:
            print(
                f"  TAILLE {r}[{k}]: dist={dist_m}m < min={spec.min_m}m",
                file=out,
            )
            ok = False
        if spec.max_m is not None and dist_m > spec.max_m:
            print(
                f"  TAILLE {r}[{k}]: dist={dist_m}m > max={spec.max_m}m",
                file=out,
            )
            ok = False
    if ok:
        print("Tailles relais : OK", file=out)
    return ok


def _check_rest(relays: list[dict], constraints: "Constraints", out) -> bool:
    """Vérifie les temps de repos entre relais consécutifs d'un même coureur."""
    relais_by_runner = _relais_by_runner(relays)
    ok = True
    for r, rels in relais_by_runner.items():
        opts = constraints.runners_data[r].options
        repos_jour_min = opts.repos_jour_min if opts.repos_jour_min is not None else constraints.defaults.repos_jour_min
        repos_nuit_min = opts.repos_nuit_min if opts.repos_nuit_min is not None else constraints.defaults.repos_nuit_min
        sorted_relais = sorted(rels, key=lambda x: x["start"])
        for i in range(len(sorted_relais) - 1):
            prev, nxt = sorted_relais[i], sorted_relais[i + 1]
            prev_spec = constraints.runners_data[r].relais[prev["k"]]
            if prev_spec.chained_to_next:
                continue
            required_min = repos_nuit_min if prev["night"] else repos_jour_min
            # Le gap temporel inclut automatiquement les pauses via cumul_temps
            gap_min = nxt["time_start_min"] - prev["time_end_min"]
            if gap_min < required_min - 0.5:
                print(
                    f"  REPOS {r}: gap={gap_min:.0f}min < {required_min:.0f}min"
                    f" (après relais k={prev['k']})",
                    file=out,
                )
                ok = False
    if ok:
        print("Repos          : OK", file=out)
    return ok


def _check_night_max(relays: list[dict], constraints: "Constraints", out) -> bool:
    """Vérifie le nombre de relais nocturnes par coureur."""
    relais_by_runner = _relais_by_runner(relays)
    ok = True
    for r, rels in relais_by_runner.items():
        opts = constraints.runners_data[r].options
        nuit_max = opts.nuit_max if opts.nuit_max is not None else constraints.defaults.nuit_max
        n = sum(1 for rel in rels if rel["night"])
        if nuit_max is not None and n > nuit_max:
            print(f"  NUIT x{n} > {nuit_max} : {r}", file=out)
            ok = False
    if ok:
        print("Nuit max       : OK", file=out)
    return ok


def _check_solo_max(relays: list[dict], constraints: "Constraints", out) -> bool:
    """Vérifie le nombre de relais solo par coureur."""
    relais_by_runner = _relais_by_runner(relays)
    ok = True
    for r, rels in relais_by_runner.items():
        opts = constraints.runners_data[r].options
        solo_max = opts.solo_max if opts.solo_max is not None else constraints.defaults.solo_max
        n = sum(1 for rel in rels if rel["solo"])
        if solo_max is not None and n > solo_max:
            print(f"  SOLO x{n} > {solo_max} : {r}", file=out)
            ok = False
    if ok:
        print("Solo max       : OK", file=out)
    return ok


def _check_solo_intervals(relays: list[dict], constraints: "Constraints", out) -> bool:
    """Vérifie que les relais solo ne chevauchent pas une zone interdite. """
    return _check_intervals(relays, constraints._intervals_no_solo, lambda r: r["solo"], "solo", out=out)


def _check_intervals(relays: list[dict], intervals: list[tuple[int,int]], filter_fn, name:str, out) -> bool:
    """Vérifie que l'intersection est vide entre 
        - les relais filtrés par filter_fn 
        - les intervalles
    """
    if not intervals:
        print(f"Intervalles {name:<20} : OK (pas de contrainte)", file=out)
        return True
    
    for (lo, hi) in intervals:
        for rel in relays:
            if filter_fn(rel) and (rel["start"] <= hi and rel["end"] > lo):
                print(
                    f"  Relais en zone {name} :"
                    f" {rel['runner']} relais k={rel['k']}"
                    f" [{rel["start"]},{rel["end"]}[ chevauche [{lo},{hi}]",
                    file=out )
                return False
    
    print(f"Intervalles {name:<20} : OK", file=out)
    return True



def _check_no_overlap_between_runners(relays: list[dict], out) -> bool:
    """Vérifie qu'aucun relais solo ne chevauche un relais d'un autre coureur.

    Les binômes partagent intentionnellement les mêmes arcs : seuls les relais
    sans partenaire commun sont vérifiés.
    """
    ok = True
    n = len(relays)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = relays[i], relays[j]
            if a["runner"] == b["runner"]:
                continue
            # Binôme : les deux relais ont le même partenaire croisé
            if a["partner"] == b["runner"] and b["partner"] == a["runner"]:
                continue
            # Chevauchement : [a_start, a_end[ ∩ [b_start, b_end[ ≠ ∅
            if a["start"] < b["end"] and b["start"] < a["end"]:
                print(
                    f"  OVERLAP : {a['runner']}[{a['k']}]=[{a['start']},{a['end']}["
                    f" chevauche {b['runner']}[{b['k']}]=[{b['start']},{b['end']}[",
                    file=out,
                )
                ok = False
    if ok:
        print("No-overlap     : OK", file=out)
    return ok


def _check_pairings(relays: list[dict], constraints: "Constraints", out) -> bool:
    """Vérifie que les SharedLeg sont bien formées dans la solution."""
    ok = True
    for r1, k1, r2, k2 in constraints.paired_relays:
        relais_r1 = [rel for rel in relays if rel["runner"] == r1 and rel["k"] == k1]
        if not relais_r1:
            print(f"  PAIRING MANQUANT : {r1}[{k1}]+{r2}[{k2}]", file=out)
            ok = False
            continue
        rel1 = relais_r1[0]
        if rel1["partner"] != r2:
            print(
                f"  PAIRING NON RESPECTÉ: {r1}[{k1}] devrait être avec {r2}"
                f" (est avec {rel1['partner']})",
                file=out,
            )
            ok = False
    if ok:
        print("Pairings       : OK", file=out)
    return ok


def _check_compatibility_matrix(relays: list[dict], constraints: "Constraints", out) -> bool:
    """Vérifie que tous les binômes actifs sont compatibles."""
    pairs = _active_pairs(relays)
    incompat = [(a, b) for a, b in pairs if constraints.compat_score(a, b) == 0]
    ok = not incompat
    if incompat:
        for a, b in incompat:
            print(f"  INCOMPATIBLE : {a}-{b}", file=out)
        print(f"Compatibilité  : ERREUR ({len(incompat)} binôme(s) incompatibles)", file=out)
    else:
        print("Compatibilité  : OK", file=out)
    n_ok        = sum(1 for a, b in pairs if constraints.compat_score(a, b) == 1)
    n_preferred = sum(1 for a, b in pairs if constraints.compat_score(a, b) == 2)
    print(f"Binômes unique : {n_ok}+{n_preferred}", file=out)
    return ok


def _check_solo(relays: list[dict], constraints: "Constraints", out) -> bool:
    """Vérifie les contraintes solo par relais."""
    ok = True
    for rel in relays:
        r, k = rel["runner"], rel["k"]
        spec = constraints.runners_data[r].relais[k]
        if spec.solo is True and not rel["solo"]:
            print(
                f"  SOLO {r}[{k}]: devrait être solo mais est en binôme",
                file=out,
            )
            ok = False
        elif spec.solo is False and rel["solo"]:
            print(
                f"  SOLO {r}[{k}]: devrait être en binôme mais est solo",
                file=out,
            )
            ok = False
    if ok:
        print("Solo forcé     : OK", file=out)
    return ok


def _check_max_duos(relays: list[dict], constraints: "Constraints", out) -> bool:
    """Vérifie les limites de binômes entre paires de coureurs (add_max_duos)."""
    if not constraints.max_duos:
        return True
    ok = True
    for r1, r2, nb_max in constraints.max_duos:
        count = sum(
            1 for rel in relays
            if rel["runner"] == r1 and rel["partner"] == r2
        )
        if count > nb_max:
            print(
                f"  MAX DUOS {r1}-{r2}: {count} binômes > max={nb_max}",
                file=out,
            )
            ok = False
    if ok:
        print("Max duos       : OK", file=out)
    return ok


def _check_chained(relays: list[dict], constraints: "Constraints", out) -> bool:
    """Vérifie que les relais enchaînés ont end[k] == start[k+1]."""
    relais_by_runner = _relais_by_runner(relays)
    ok = True
    for r, rels in relais_by_runner.items():
        by_k = {rel["k"]: rel for rel in rels}
        for k, spec in enumerate(constraints.runners_data[r].relais):
            if spec.chained_to_next and k in by_k and k + 1 in by_k:
                if by_k[k]["end"] != by_k[k + 1]["start"]:
                    print(
                        f"  CHAINED {r}[{k}]: end={by_k[k]['end']} != start[{k+1}]={by_k[k+1]['start']}",
                        file=out,
                    )
                    ok = False
    if ok:
        print("Enchaînements  : OK", file=out)
    return ok


def _check_max_same_partenaire(relays: list[dict], constraints: "Constraints", out) -> bool:
    """Vérifie la limite de binômes avec un même partenaire par coureur."""
    relais_by_runner = _relais_by_runner(relays)
    ok = True
    for r, rels in relais_by_runner.items():
        opts = constraints.runners_data[r].options
        limit = opts.max_same_partenaire if opts.max_same_partenaire is not None else constraints.defaults.max_same_partenaire
        if limit is None:
            continue
        partner_count: dict[str, int] = {}
        for rel in rels:
            if rel["partner"] is not None:
                partner_count[rel["partner"]] = partner_count.get(rel["partner"], 0) + 1
        for partner, count in partner_count.items():
            if count > limit:
                print(
                    f"  MAX SAME PARTENAIRE {r}: {count} binômes avec {partner} > max={limit}",
                    file=out,
                )
                ok = False
    if ok:
        print("Max partenaire : OK", file=out)
    return ok


def _check_availability(relays: list[dict], constraints: "Constraints", out) -> bool:
    """Vérifie que chaque relais respecte sa fenêtre de disponibilité (window)."""
    ok = True
    for rel in relays:
        r, k = rel["runner"], rel["k"]
        spec = constraints.runners_data[r].relais[k]
        if spec.window is None:
            continue
        start, end = rel["start"], rel["end"]
        if not any(lo <= start and end <= hi for lo, hi in spec.window):
            print(
                f"  DISPONIBILITÉ {r}[{k}]: [{start},{end}] hors fenêtre {spec.window}",
                file=out,
            )
            ok = False
    if ok:
        print("Disponibilité  : OK", file=out)
    return ok


def _check_pinned(relays: list[dict], constraints: "Constraints", out) -> bool:
    """Vérifie que les relais épinglés respectent leurs points fixés."""
    ok = True
    for rel in relays:
        r, k = rel["runner"], rel["k"]
        spec = constraints.runners_data[r].relais[k]
        if spec.pinned_start is not None and rel["start"] != spec.pinned_start:
            print(
                f"  PINNED {r}[{k}]: start={rel['start']} != pinned_start={spec.pinned_start}",
                file=out,
            )
            ok = False
        if spec.pinned_end is not None and rel["end"] != spec.pinned_end:
            print(
                f"  PINNED {r}[{k}]: end={rel['end']} != pinned_end={spec.pinned_end}",
                file=out,
            )
            ok = False
    if ok:
        print("Épinglages     : OK", file=out)
    return ok


def _check_dplus_max(relays: list[dict], constraints: "Constraints", out) -> bool:
    """Vérifie que le D+ + D- de chaque relais ne dépasse pas dplus_max."""
    ok = True
    for rel in relays:
        r, k = rel["runner"], rel["k"]
        spec = constraints.runners_data[r].relais[k]
        if spec.dplus_max is None:
            continue
        d_plus = rel.get("d_plus")
        d_moins = rel.get("d_moins")
        if d_plus is None or d_moins is None:
            continue
        total = d_plus + d_moins
        if total > spec.dplus_max + 0.5:
            print(
                f"  DPLUS_MAX {r}[{k}]: D+/D-={total:.0f}m > max={spec.dplus_max}m",
                file=out,
            )
            ok = False
    if ok:
        print("D+ max         : OK", file=out)
    return ok


def _check_night_vs_time(relays: list[dict], constraints: "Constraints", out) -> bool:
    """Vérifie la cohérence entre le flag night et les intervalles nocturnes.

    Un relais est nocturne ssi il chevauche au moins un intervalle de nuit
    (start <= hi AND end > lo). Détecte les incohérences dans les deux sens.
    """
    if not constraints._intervals_night:
        print("Nuit vs heure  : OK (pas d'intervalle nocturne)", file=out)
        return True
    ok = True
    for rel in relays:
        r, k = rel["runner"], rel["k"]
        s, e = rel["start"], rel["end"]
        overlaps_night = any(s <= hi and e > lo for lo, hi in constraints._intervals_night)
        if rel["night"] and not overlaps_night:
            print(
                f"  NUIT/HEURE {r}[{k}]: night=true mais le relais [{s},{e}["
                f" ne chevauche aucun intervalle nocturne",
                file=out,
            )
            ok = False
        elif not rel["night"] and overlaps_night:
            print(
                f"  NUIT/HEURE {r}[{k}]: night=false mais le relais [{s},{e}["
                f" chevauche un intervalle nocturne",
                file=out,
            )
            ok = False
    if ok:
        print("Nuit vs heure  : OK", file=out)
    return ok


def _check_solo_vs_partner(relays: list[dict], out) -> bool:
    """Vérifie la cohérence entre solo et partner.

    solo=true implique partner=None, solo=false implique partner renseigné.
    """
    ok = True
    for rel in relays:
        r, k = rel["runner"], rel["k"]
        if rel["solo"] and rel["partner"] is not None:
            print(
                f"  SOLO/PARTNER {r}[{k}]: solo=true mais partner={rel['partner']}",
                file=out,
            )
            ok = False
        elif not rel["solo"] and rel["partner"] is None:
            print(
                f"  SOLO/PARTNER {r}[{k}]: solo=false mais partner=None",
                file=out,
            )
            ok = False
    if ok:
        print("Solo/partner   : OK", file=out)
    return ok


def _check_partner_reciprocity(relays: list[dict], out) -> bool:
    """Vérifie que les binômes sont réciproques.

    Si A[k] déclare partner=B, il doit exister un relais de B avec
    partner=A couvrant exactement les mêmes arcs (start et end identiques).
    """
    ok = True
    for rel in relays:
        if rel["partner"] is None:
            continue
        r, k = rel["runner"], rel["k"]
        partner = rel["partner"]
        match = [
            other for other in relays
            if other["runner"] == partner
            and other["partner"] == r
            and other["start"] == rel["start"]
            and other["end"] == rel["end"]
        ]
        if not match:
            print(
                f"  RÉCIPROCITÉ {r}[{k}]: partner={partner}"
                f" mais aucun relais réciproque trouvé"
                f" (même start={rel['start']}, end={rel['end']}, partner={r})",
                file=out,
            )
            ok = False
    if ok:
        print("Réciprocité    : OK", file=out)
    return ok


def _check_km_consistency(relays: list[dict], out) -> bool:
    """Vérifie que km ≈ km_end - km_start."""
    TOL_KM = 0.01  # 10 m
    ok = True
    for rel in relays:
        if "km_start" not in rel or "km_end" not in rel:
            continue
        r, k = rel["runner"], rel["k"]
        expected = rel["km_end"] - rel["km_start"]
        if abs(rel["km"] - expected) > TOL_KM:
            print(
                f"  KM {r}[{k}]: km={rel['km']:.3f}"
                f" != km_end-km_start={expected:.3f}",
                file=out,
            )
            ok = False
    if ok:
        print("Km cohérence   : OK", file=out)
    return ok


def _check_start_end_order(relays: list[dict], constraints: "Constraints", out) -> bool:
    """Vérifie que start < end et que les indices sont dans les bornes."""
    ok = True
    for rel in relays:
        r, k = rel["runner"], rel["k"]
        s, e = rel["start"], rel["end"]
        if s >= e:
            print(
                f"  ORDRE {r}[{k}]: start={s} >= end={e}",
                file=out,
            )
            ok = False
        if s < 0 or e > constraints.nb_points - 1:
            print(
                f"  BORNES {r}[{k}]: start={s} end={e}"
                f" hors [0, {constraints.nb_points - 1}]",
                file=out,
            )
            ok = False
    if ok:
        print("Ordre/bornes   : OK", file=out)
    return ok
