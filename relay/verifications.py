from .constraints import Constraints


class _NullWriter:
    def write(self, *_): pass
    def flush(self): pass

_NULL = _NullWriter()


def check(solution, out=_NULL) -> bool:
    """Vérifie la cohérence de la solution courante. solution est une Solution."""
    relays = solution.relays
    constraints = solution.constraints

    print("\n--- Vérifications ---", file=out)

    if not _check_unknown_runners(relays, constraints, out):
        return False

    ok = True
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

    return ok


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _relais_by_runner(solution: list[dict]) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for rel in solution:
        result.setdefault(rel["runner"], []).append(rel)
    return result


def _active_pairs(solution: list[dict]) -> list[tuple[str, str]]:
    pairs = []
    seen: set[frozenset] = set()
    for rel in solution:
        if rel["partner"] is not None:
            key = frozenset({rel["runner"], rel["partner"]})
            if key not in seen:
                seen.add(key)
                pairs.append((rel["runner"], rel["partner"]))
    return pairs


# ------------------------------------------------------------------
# Vérifications post-résolution
# ------------------------------------------------------------------

def _check_unknown_runners(solution: list[dict], constraints: Constraints, out) -> bool:
    unknown = {rel["runner"] for rel in solution if rel["runner"] not in constraints.runners_data}
    if unknown:
        for r in sorted(unknown):
            print(f"  COUREUR INCONNU : {r} (absent des contraintes courantes)", file=out)
        return False
    return True


def _check_pauses(solution: list[dict], constraints: Constraints, out) -> bool:
    ok = True
    inactive = constraints.inactive_segments
    for rel in solution:
        for s in range(rel["start"], rel["end"]):
            if s in inactive:
                print(
                    f"  PAUSE FRANCHIE : {rel['runner']}[{rel['k']}]=[{rel['start']},{rel['end']}["
                    f" couvre le segment inactif {s}",
                    file=out,
                )
                ok = False
                break
    if ok:
        print("Pauses         : OK", file=out)
    return ok


def _check_relay_sizes(solution: list[dict], constraints: Constraints, out) -> bool:
    ok = True
    for rel in solution:
        r, k = rel["runner"], rel["k"]
        size = rel["size"]
        length = rel["end"] - rel["start"]
        allowed = constraints.runners_data[r].relais[k].size
        if length != size:
            print(f"  TAILLE {r}[{k}]: end-start={length} ≠ size={size}", file=out)
            ok = False
        if size not in allowed:
            print(f"  TAILLE {r}[{k}]: size={size} ∉ autorisé={allowed}", file=out)
            ok = False
    if ok:
        print("Tailles relais : OK", file=out)
    return ok


def _check_coverage(solution: list[dict], constraints: Constraints, out) -> bool:
    coverage = [0] * constraints.nb_segments
    for rel in solution:
        for seg in range(rel["start"], rel["end"]):
            coverage[seg] += 1
    active = constraints.active_segments
    gaps = [s for s in active if coverage[s] == 0]
    over = [s for s in range(constraints.nb_segments) if coverage[s] > 2]
    ok = not gaps and not over
    print(
        f"Couverture     : {'OK' if ok else f'ERREUR gaps={gaps} over={over}'}",
        file=out,
    )
    return ok


def _check_rest(solution: list[dict], constraints: Constraints, out) -> bool:
    relais = _relais_by_runner(solution)
    sd = constraints.segment_duration  # heures par quantum de temps
    ok = True
    for r, rels in relais.items():
        opts = constraints.runners_data[r].options
        repos_jour_h = opts.repos_jour * sd
        repos_nuit_h = opts.repos_nuit * sd
        sorted_relais = sorted(rels, key=lambda x: x["start"])
        for i in range(len(sorted_relais) - 1):
            prev, nxt = sorted_relais[i], sorted_relais[i + 1]
            required_h = repos_nuit_h if prev["night"] else repos_jour_h
            # Dans le modèle espace-temps, le gap inclut automatiquement les pauses.
            gap_h = (nxt["start"] - prev["end"]) * sd
            if gap_h < required_h - 1e-9:
                print(f"  REPOS {r}: gap={gap_h:.2f}h < {required_h:.2f}h", file=out)
                ok = False
    if ok:
        print("Repos          : OK", file=out)
    return ok


def _check_night_max(solution: list[dict], constraints: Constraints, out) -> bool:
    relais = _relais_by_runner(solution)
    ok = True
    for r, rels in relais.items():
        nuit_max = constraints.runners_data[r].options.nuit_max
        n = sum(1 for rel in rels if rel["night"])
        if n > nuit_max:
            print(f"  NUIT x{n} : {r}", file=out)
            ok = False
    if ok:
        print("Nuit ×1        : OK", file=out)
    return ok


def _check_solo_max(solution: list[dict], constraints: Constraints, out) -> bool:
    relais = _relais_by_runner(solution)
    ok = True
    for r, rels in relais.items():
        solo_max = constraints.runners_data[r].options.solo_max
        n = sum(1 for rel in rels if rel["solo"])
        if n > solo_max:
            print(f"  SOLO x{n} : {r}", file=out)
            ok = False
    if ok:
        print("Solo ≤ 1       : OK", file=out)
    return ok


def _check_solo_intervals(solution: list[dict], constraints: Constraints, out) -> bool:
    forbidden = constraints.solo_forbidden_segments
    ok = True
    for rel in solution:
        if rel["solo"] and rel["start"] in forbidden:
            print(f"  SOLO hors [{constraints.solo_autorise_debut}h–{constraints.solo_autorise_fin}h]: {rel['runner']} relais k={rel['k']}", file=out)
            ok = False
    if ok:
        print(f"Solo [{constraints.solo_autorise_debut}h–{constraints.solo_autorise_fin}h]: OK", file=out)
    return ok


def _check_no_overlap_between_runners(solution: list[dict], out) -> bool:
    """Vérifie qu'aucun relais solo ne chevauche un relais d'un autre coureur.

    Les binômes (partner != None) partagent intentionnellement les mêmes segments :
    seuls les relais sans partenaire commun sont vérifiés.
    """
    ok = True
    n = len(solution)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = solution[i], solution[j]
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


def _check_pairings(solution: list[dict], constraints: Constraints, out) -> bool:
    ok = True
    for r1, k1, r2, k2 in constraints.paired_relays:
        # Vérifie que r1[k1] et r2[k2] forment bien un binôme dans la solution
        relais_r1 = [rel for rel in solution if rel["runner"] == r1 and rel["k"] == k1]
        if not relais_r1:
            print(f"  PAIRING MANQUANT (index hors bornes): {r1}[{k1}]+{r2}[{k2}]", file=out)
            ok = False
            continue
        rel1 = relais_r1[0]
        if rel1["partner"] != r2:
            print(f"  PAIRING NON RESPECTÉ: {r1}[{k1}] devrait être avec {r2} (est avec {rel1['partner']})", file=out)
            ok = False
    if ok:
        print("Pairings       : OK", file=out)
    return ok


def _check_compatibility_matrix(solution: list[dict], constraints: Constraints, out) -> bool:
    pairs = _active_pairs(solution)
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
