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
    ok &= _check_rest(solution, constraints, out)
    ok &= _check_night_max(solution, constraints, out)
    ok &= _check_solo_max(solution, constraints, out)
    ok &= _check_solo_night(solution, out)
    ok &= _check_pair_at_least_once(solution, constraints, out)
    ok &= _check_pair_at_most_once(solution, constraints, out)
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
        repos_jour = constraints.runners_data[r].repos_jour
        repos_nuit = constraints.runners_data[r].repos_nuit
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
        nuit_max = constraints.runners_data[r].nuit_max
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
        solo_max = constraints.runners_data[r].solo_max
        n = sum(1 for rel in rels if rel["solo"])
        if n > solo_max:
            print(f"  SOLO x{n} : {r}", file=out)
            ok = False
    if ok:
        print("Solo ≤ 1       : OK", file=out)
    return ok


def _check_solo_night(solution: list[dict], out) -> bool:
    ok = True
    for rel in solution:
        if rel["solo"] and rel["night"]:
            print(f"  SOLO+NUIT       : {rel['runner']} relais k={rel['k']}", file=out)
            ok = False
    if ok:
        print("Solo≠Nuit      : OK", file=out)
    return ok


def _active_pairs_set(solution: list[dict]) -> list[frozenset]:
    return [frozenset({rel["runner"], rel["partner"]}) for rel in solution if rel["partner"] is not None]


def _check_pair_at_least_once(solution: list[dict], constraints: RelayConstraints, out) -> bool:
    pair_sets = _active_pairs_set(solution)
    ok = True
    for r1, r2 in constraints.binomes_once_min:
        if frozenset({r1, r2}) not in pair_sets:
            print(f"  BINÔME OBLIGATOIRE MANQUANT: {r1}-{r2}", file=out)
            ok = False
    return ok


def _check_pair_at_most_once(solution: list[dict], constraints: RelayConstraints, out) -> bool:
    # Chaque binôme produit 2 entrées dans _active_pairs_set (une par coureur) : on divise par 2
    pair_sets = _active_pairs_set(solution)
    ok = True
    for r1, r2 in constraints.binomes_once_max:
        count = pair_sets.count(frozenset({r1, r2})) // 2
        if count > 1:
            print(f"  BINÔME EN TROP: {r1}-{r2} ({count} relais ensemble)", file=out)
            ok = False
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
