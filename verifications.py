from constraints import RelayConstraints


class _NullWriter:
    def write(self, *_): pass
    def flush(self): pass

_NULL = _NullWriter()


def check(solution: list[dict], constraints: RelayConstraints, out=_NULL) -> bool:
    """Vérifie la cohérence de la solution courante. Sans argument, la sortie est désactivée."""

    print("\n--- Vérifications ---", file=out)

    ok = True
    ok &= _check_coverage(solution, constraints, out)
    ok &= _check_pauses(solution, constraints, out)
    ok &= _check_relay_sizes(solution, constraints, out)
    ok &= _check_rest(solution, constraints, out)
    ok &= _check_night_max(solution, constraints, out)
    ok &= _check_solo_max(solution, constraints, out)
    ok &= _check_solo_intervals(solution, constraints, out)
    ok &= _check_no_overlap_between_runners(solution, out)
    ok &= _check_pairings(solution, constraints, out)
    ok &= _check_compatibility_matrix(solution, constraints, out)

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

def _check_pauses(solution: list[dict], constraints: RelayConstraints, out) -> bool:
    ok = True
    for rel in solution:
        for ps in constraints.pause_segments:
            if rel["start"] < ps < rel["end"]:
                print(
                    f"  PAUSE FRANCHIE : {rel['runner']}[{rel['k']}]=[{rel['start']},{rel['end']}["
                    f" franchit la frontière de pause seg {ps}",
                    file=out,
                )
                ok = False
    if ok:
        print("Pauses         : OK", file=out)
    return ok


def _check_relay_sizes(solution: list[dict], constraints: RelayConstraints, out) -> bool:
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


def _check_coverage(solution: list[dict], constraints: RelayConstraints, out) -> bool:
    coverage = [0] * constraints.nb_segments
    for rel in solution:
        for seg in range(rel["start"], rel["end"]):
            coverage[seg] += 1
    gaps = [s for s in range(constraints.nb_segments) if coverage[s] == 0]
    over = [s for s in range(constraints.nb_segments) if coverage[s] > 2]
    ok = not gaps and not over
    print(
        f"Couverture     : {'OK' if ok else f'ERREUR gaps={gaps} over={over}'}",
        file=out,
    )
    return ok


def _check_rest(solution: list[dict], constraints: RelayConstraints, out) -> bool:
    relais = _relais_by_runner(solution)
    ok = True
    for r, rels in relais.items():
        repos_jour = constraints._resolved_repos_jour(constraints.runners_data[r])
        repos_nuit = constraints._resolved_repos_nuit(constraints.runners_data[r])
        sorted_relais = sorted(rels, key=lambda x: x["start"])
        for i in range(len(sorted_relais) - 1):
            prev, nxt = sorted_relais[i], sorted_relais[i + 1]
            required = repos_nuit if prev["night"] else repos_jour
            gap = nxt["start"] - prev["end"]
            if gap < required:
                print(f"  REPOS {r}: gap={gap} < {required}", file=out)
                ok = False
    if ok:
        print("Repos          : OK", file=out)
    return ok


def _check_night_max(solution: list[dict], constraints: RelayConstraints, out) -> bool:
    relais = _relais_by_runner(solution)
    ok = True
    for r, rels in relais.items():
        nuit_max = constraints._resolved_nuit_max(constraints.runners_data[r])
        n = sum(1 for rel in rels if rel["night"])
        if n > nuit_max:
            print(f"  NUIT x{n} : {r}", file=out)
            ok = False
    if ok:
        print("Nuit ×1        : OK", file=out)
    return ok


def _check_solo_max(solution: list[dict], constraints: RelayConstraints, out) -> bool:
    relais = _relais_by_runner(solution)
    ok = True
    for r, rels in relais.items():
        solo_max = constraints._resolved_solo_max(constraints.runners_data[r])
        n = sum(1 for rel in rels if rel["solo"])
        if n > solo_max:
            print(f"  SOLO x{n} : {r}", file=out)
            ok = False
    if ok:
        print("Solo ≤ 1       : OK", file=out)
    return ok


def _check_solo_intervals(solution: list[dict], constraints: RelayConstraints, out) -> bool:
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


def _check_pairings(solution: list[dict], constraints: RelayConstraints, out) -> bool:
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


def _check_compatibility_matrix(solution: list[dict], constraints: RelayConstraints, out) -> bool:
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
