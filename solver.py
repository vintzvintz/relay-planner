"""
Solveur CP-SAT — relais Lyon-Fessenheim.

Reformulation sans variables covers :
- Couverture via add_cumulative (demande=1 par relais, capacité=2, borne inf=1)
- Cohérence binôme via : deux relais compatibles de même taille sont soit
  identiques (same_relay=1) soit disjoints (pas de chevauchement partiel)
"""

from ortools.sat.python import cp_model
from print_solution import save_solution
from data import (
    N_SEGMENTS,
    RUNNER_RELAYS,
    UNAVAILABILITY,
    REST_NORMAL,
    REST_NIGHT,
    NIGHT_SEGMENTS,
    OLIVIER_NIGHT1,
    OLIVIER_NIGHT2,
    COMPATIBLE,
    MANDATORY_PAIRS,
    MULTI_NIGHT_ALLOWED,
)

RUNNERS = list(RUNNER_RELAYS.keys())
N_RUNNERS = len(RUNNERS)
SEG_NIGHT_LIST = sorted(NIGHT_SEGMENTS)

# Paramètres solveur
SOLVER_TIME_LIMIT = 60.0  # secondes
SOLVER_NUM_WORKERS = 8


def _add_variables(model):
    """Crée les variables start/end et intervalles pour chaque relais.

    Pour chaque coureur r et relais k de taille sz :
    - start[r][k] ∈ [0, N_SEGMENTS - sz]
    - end[r][k] = start[r][k] + sz  (fixé par contrainte)
    - Un interval_var liant start, sz et end (utilisé par add_no_overlap et add_cumulative)

    Contrainte intra-coureur : les relais d'un même coureur ne se chevauchent pas.
    """
    start, end, intervals_all = {}, {}, []
    for r in RUNNERS:
        start[r], end[r] = [], []
        runner_ivs = []
        for k, sz in enumerate(RUNNER_RELAYS[r]):
            s = model.new_int_var(0, N_SEGMENTS - sz, f"s_{r}_{k}")
            e = model.new_int_var(sz, N_SEGMENTS, f"e_{r}_{k}")
            model.add(e == s + sz)
            iv = model.new_interval_var(s, sz, e, f"iv_{r}_{k}")
            start[r].append(s)
            end[r].append(e)
            intervals_all.append((r, k, sz, iv))
            runner_ivs.append(iv)
        if len(runner_ivs) > 1:
            model.add_no_overlap(runner_ivs)
    return start, end, intervals_all


def _add_night_relay(model, start):
    """Crée les variables booléennes night_relay[r][k] et applique la contrainte nuit.

    night_relay[r][k] = 1 ssi le relais k du coureur r est un relais de nuit,
    c'est-à-dire qu'il couvre au moins un segment nocturne (0h–6h).

    Un relais couvre au moins un segment nocturne ssi son start appartient à
    l'ensemble des positions de départ qui intersectent la nuit.

    Contrainte : sauf exception (MULTI_NIGHT_ALLOWED), chaque coureur effectue
    au plus 1 relais de nuit.
    """
    night_relay = {}
    for r in RUNNERS:
        night_relay[r] = []
        for k, sz in enumerate(RUNNER_RELAYS[r]):
            # Positions de départ qui donnent un relais nocturne :
            # le relais [start, start+sz[ contient au moins un segment n ∈ NIGHT_SEGMENTS
            # ⟺ start ∈ [n - sz + 1, n] pour au moins un n nocturne.
            night_starts = sorted(
                set(
                    n - off
                    for n in SEG_NIGHT_LIST
                    for off in range(sz)
                    if 0 <= n - off <= N_SEGMENTS - sz
                )
            )
            rhn = model.new_bool_var(f"rn_{r}_{k}")
            if not night_starts:
                model.add(rhn == 0)
            else:
                nd = cp_model.Domain.from_values(night_starts)
                dd = nd.complement().intersection_with(
                    cp_model.Domain(0, N_SEGMENTS - sz)
                )
                model.add_linear_expression_in_domain(start[r][k], nd).only_enforce_if(rhn)
                if not dd.is_empty():
                    model.add_linear_expression_in_domain(
                        start[r][k], dd
                    ).only_enforce_if(~rhn)
                else:
                    model.add(rhn == 1)
            night_relay[r].append(rhn)

    for r in RUNNERS:
        if r not in MULTI_NIGHT_ALLOWED:
            model.add(sum(night_relay[r]) <= 1)

    return night_relay


def _add_rest_constraints(model, start, end, night_relay):
    """Repos minimum entre toute paire de relais d'un même coureur.

    Pour chaque paire (k, kp) de relais du coureur r, une variable booléenne b
    indique l'ordre temporel : b=1 signifie que k précède kp.

    Le repos requis dépend du type du relais qui précède :
    - Relais de jour  → REST_NORMAL segments de repos
    - Relais de nuit  → REST_NIGHT segments de repos
    """
    for r in RUNNERS:
        n = len(RUNNER_RELAYS[r])
        if n < 2:
            continue
        for k in range(n):
            for kp in range(k + 1, n):
                b = model.new_bool_var(f"bef_{r}_{k}_{kp}")
                # k avant kp
                bkd = model.new_bool_var(f"bkd_{r}_{k}_{kp}")  # k précède, jour
                bkn = model.new_bool_var(f"bkn_{r}_{k}_{kp}")  # k précède, nuit
                model.add_bool_and([b, ~night_relay[r][k]]).only_enforce_if(bkd)
                model.add_bool_or([~b, night_relay[r][k]]).only_enforce_if(~bkd)
                model.add_bool_and([b, night_relay[r][k]]).only_enforce_if(bkn)
                model.add_bool_or([~b, ~night_relay[r][k]]).only_enforce_if(~bkn)
                model.add(end[r][k] + REST_NORMAL <= start[r][kp]).only_enforce_if(bkd)
                model.add(end[r][k] + REST_NIGHT <= start[r][kp]).only_enforce_if(bkn)
                # kp avant k
                bkpd = model.new_bool_var(f"bkpd_{r}_{k}_{kp}")  # kp précède, jour
                bkpn = model.new_bool_var(f"bkpn_{r}_{k}_{kp}")  # kp précède, nuit
                model.add_bool_and([~b, ~night_relay[r][kp]]).only_enforce_if(bkpd)
                model.add_bool_or([b, night_relay[r][kp]]).only_enforce_if(~bkpd)
                model.add_bool_and([~b, night_relay[r][kp]]).only_enforce_if(bkpn)
                model.add_bool_or([b, ~night_relay[r][kp]]).only_enforce_if(~bkpn)
                model.add(end[r][kp] + REST_NORMAL <= start[r][k]).only_enforce_if(bkpd)
                model.add(end[r][kp] + REST_NIGHT <= start[r][k]).only_enforce_if(bkpn)


def _add_availability(model, start, end):
    """Applique les indisponibilités et affectations fixes.

    UNAVAILABILITY[r] est une liste de fenêtres (debut, fin) en segments
    pendant lesquelles le coureur r ne peut pas commencer un relais.
    Tout relais doit donc être entièrement en dehors de ces fenêtres.

    Contraintes spéciales :
    - Clémence : indisponible entre ses deux fenêtres de course (voir UNAVAILABILITY).
      Relais 0 avant la fenêtre interdite, relais 1 après.
    - Olivier  : ses 2 relais de 30km sont calés sur des fenêtres nocturnes précises.
    - Alexis   : forcé au même start qu'Olivier sur les 30km (binôme obligatoire).
    """
    # Indisponibilités générales
    for r, windows in UNAVAILABILITY.items():
        for (unavail_start, unavail_end) in windows:
            for k in range(len(RUNNER_RELAYS[r])):
                # Le relais [s, s+sz[ doit être hors de [unavail_start, unavail_end[
                # ⟺ s+sz <= unavail_start  OR  s >= unavail_end
                before = model.new_bool_var(f"unavail_before_{r}_{k}")
                model.add(end[r][k] <= unavail_start).only_enforce_if(before)
                model.add(start[r][k] >= unavail_end).only_enforce_if(~before)

    # Clémence : relais 0 avant la fenêtre interdite, relais 1 après
    if "Clemence" in UNAVAILABILITY and UNAVAILABILITY["Clemence"]:
        unavail_start, unavail_end = UNAVAILABILITY["Clemence"][0]
        model.add(end["Clemence"][0] <= unavail_start)
        model.add(start["Clemence"][1] >= unavail_end)

    # Olivier : ses 2 relais de 30km (sz=6) sont ancrés sur les fenêtres nocturnes
    # start ∈ [ns - 2, ns] pour laisser 2 segments flottants avant la fenêtre 0h-2h
    o30 = [k for k, sz in enumerate(RUNNER_RELAYS["Olivier"]) if sz == 6][:2]
    a30 = [k for k, sz in enumerate(RUNNER_RELAYS["Alexis"]) if sz == 6][:2]
    for ok, ak, nw in zip(o30, a30, [OLIVIER_NIGHT1, OLIVIER_NIGHT2]):
        ns = nw[0]
        model.add(start["Olivier"][ok] >= max(0, ns - 2))
        model.add(start["Olivier"][ok] <= ns)
        # Alexis court en binôme avec Olivier sur ces relais
        model.add(start["Alexis"][ak] == start["Olivier"][ok])


def _add_same_relay(model, start):
    """Crée les variables same_relay[(r,k,rp,kp)] pour les binômes potentiels.

    same_relay[(r,k,rp,kp)] = 1 ssi les relais k de r et kp de rp commencent
    au même segment (et ont la même taille), formant un binôme.

    Condition nécessaire pour créer la variable : r et rp sont compatibles
    (COMPATIBLE) et leurs relais ont la même taille.

    Si same_relay = 0, les deux relais sont forcés disjoints (pas de
    chevauchement partiel autorisé : diff ≥ sz ou diff ≤ -sz).
    """
    same_relay = {}
    for ri, r in enumerate(RUNNERS):
        for k, sz_r in enumerate(RUNNER_RELAYS[r]):
            for rpi in range(ri + 1, N_RUNNERS):
                rp = RUNNERS[rpi]
                if rp not in COMPATIBLE.get(r, set()):
                    continue
                for kp, sz_rp in enumerate(RUNNER_RELAYS[rp]):
                    if sz_r != sz_rp:
                        continue
                    key = (r, k, rp, kp)
                    b = model.new_bool_var(f"sr_{r}_{k}_{rp}_{kp}")
                    same_relay[key] = b
                    model.add(start[r][k] == start[rp][kp]).only_enforce_if(b)
                    diff = model.new_int_var(
                        -N_SEGMENTS, N_SEGMENTS, f"d_{r}_{k}_{rp}_{kp}"
                    )
                    model.add(diff == start[r][k] - start[rp][kp])
                    # b=0 → |diff| >= sz_r (pas de chevauchement partiel)
                    no_overlap_dom = cp_model.Domain(-N_SEGMENTS, -sz_r).union_with(
                        cp_model.Domain(sz_r, N_SEGMENTS)
                    )
                    model.add_linear_expression_in_domain(
                        diff, no_overlap_dom
                    ).only_enforce_if(~b)
    return same_relay


def _add_coverage(model, start, intervals_all):
    """Contrainte de couverture : chaque segment doit être couvert par 1 ou 2 relais.

    add_cumulative garantit la borne haute (≤ 2 relais par segment).
    La borne basse (≥ 1) est assurée par une somme de booléens covers_s pour
    chaque segment s, où covers_s[r][k] = 1 ssi le relais k de r couvre s.
    """
    all_ivs = [iv for _, _, _, iv in intervals_all]
    all_demand = [1 for _ in intervals_all]
    # Au plus 2 relais simultanés (cumulative borne haute)
    model.add_cumulative(all_ivs, all_demand, 2)

    # Au moins 1 relais par segment (borne basse)
    for s in range(N_SEGMENTS):
        covers_s = []
        for r in RUNNERS:
            for k, sz in enumerate(RUNNER_RELAYS[r]):
                # Le relais k couvre s ssi start[r][k] ∈ [max(0, s-sz+1), min(s, N-sz)]
                lo = max(0, s - sz + 1)
                hi = min(s, N_SEGMENTS - sz)
                if lo > hi:
                    continue
                b = model.new_bool_var(f"c_{r}_{k}_{s}")
                dom_in = cp_model.Domain(lo, hi)
                dom_out = dom_in.complement().intersection_with(
                    cp_model.Domain(0, N_SEGMENTS - sz)
                )
                model.add_linear_expression_in_domain(
                    start[r][k], dom_in
                ).only_enforce_if(b)
                if not dom_out.is_empty():
                    model.add_linear_expression_in_domain(
                        start[r][k], dom_out
                    ).only_enforce_if(~b)
                covers_s.append(b)
        model.add(sum(covers_s) >= 1)


def _add_inter_runner_no_overlap(model, intervals_all, same_relay):
    """Force la disjonction entre relais de coureurs différents non binômables.

    Deux relais peuvent se chevaucher uniquement s'ils forment un binôme
    (same_relay = 1). Pour toutes les paires non couvertes par same_relay
    (coureurs incompatibles ou tailles différentes), on impose la disjonction
    via add_no_overlap.
    """
    for ri, r in enumerate(RUNNERS):
        for k, _ in enumerate(RUNNER_RELAYS[r]):
            iv_rk = intervals_all[
                [
                    i
                    for i, (rr, kk, _, _) in enumerate(intervals_all)
                    if rr == r and kk == k
                ][0]
            ][3]
            for rpi in range(ri + 1, N_RUNNERS):
                rp = RUNNERS[rpi]
                for kp, _ in enumerate(RUNNER_RELAYS[rp]):
                    iv_rpkp = intervals_all[
                        [
                            i
                            for i, (rr, kk, _, _) in enumerate(intervals_all)
                            if rr == rp and kk == kp
                        ][0]
                    ][3]
                    key = (r, k, rp, kp)
                    key_rev = (rp, kp, r, k)
                    if key in same_relay or key_rev in same_relay:
                        continue
                    model.add_no_overlap([iv_rk, iv_rpkp])


def _add_solo_constraints(model, same_relay):
    """Crée les variables relais_solo[r][k] et limite à au plus 1 solo par coureur.

    relais_solo[r][k] = 1 ssi aucun partenaire n'est affecté au relais k de r.
    Un coureur peut effectuer au plus 1 relais en solo sur toute la course.
    """
    relais_solo = {}
    for r in RUNNERS:
        relais_solo[r] = []
        for k in range(len(RUNNER_RELAYS[r])):
            # Toutes les variables same_relay impliquant ce relais
            partners = [
                bv
                for key, bv in same_relay.items()
                if (key[0] == r and key[1] == k) or (key[2] == r and key[3] == k)
            ]
            b = model.new_bool_var(f"solo_{r}_{k}")
            if partners:
                # solo = 1 ⟺ aucun partenaire actif
                model.add_bool_or(partners).only_enforce_if(~b)
                model.add_bool_and([~p for p in partners]).only_enforce_if(b)
            else:
                # Aucun binôme possible : relais forcément solo
                model.add(b == 1)
            relais_solo[r].append(b)

    for r in RUNNERS:
        model.add(sum(relais_solo[r]) <= 1)

    return relais_solo


def _add_no_solo_night(model, relais_solo, night_relay):
    """Interdit les relais solo la nuit : solo[r][k] + night[r][k] <= 1."""
    for r in RUNNERS:
        for k in range(len(RUNNER_RELAYS[r])):
            model.add(relais_solo[r][k] + night_relay[r][k] <= 1)


def _add_mandatory_pairs(model, same_relay):
    """Impose qu'au moins un relais en binôme soit partagé pour chaque paire obligatoire.

    Pour chaque paire (r1, r2) de MANDATORY_PAIRS, au moins une variable
    same_relay les liant doit valoir 1.
    """
    for r1, r2 in MANDATORY_PAIRS:
        pair_vars = [
            bv
            for key, bv in same_relay.items()
            if (key[0] == r1 and key[2] == r2) or (key[0] == r2 and key[2] == r1)
        ]
        if pair_vars:
            model.add_bool_or(pair_vars)
        else:
            print(f"AVERTISSEMENT: aucun binôme possible {r1}-{r2}")


def _solve_and_save(model, start, same_relay, relais_solo, night_relay):
    """Lance la résolution CP-SAT et délègue l'affichage/sauvegarde à print_solution."""
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_TIME_LIMIT
    solver.parameters.log_search_progress = True
    solver.parameters.num_workers = SOLVER_NUM_WORKERS

    print("Résolution en cours...")
    status = solver.solve(model)

    print(f"\nStatut : {solver.status_name(status)}")
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print(f"Binômes : {int(solver.objective_value)}\n")
        save_solution(solver, start, same_relay, relais_solo, night_relay)
    else:
        print("Aucune solution trouvée.")

    return solver, status


def build_and_solve():
    """Construit le modèle CP-SAT et lance la résolution.

    Enchaîne toutes les étapes de modélisation dans l'ordre :
    variables → no-overlap intra → nuit → repos → disponibilités →
    same_relay → couverture → no-overlap inter → solo → binômes obligatoires →
    objectif (maximiser les binômes).

    Retourne (solver, status) après résolution.
    """
    model = cp_model.CpModel()

    start, end, intervals_all = _add_variables(model)
    night_relay = _add_night_relay(model, start)
    _add_rest_constraints(model, start, end, night_relay)
    _add_availability(model, start, end)
    same_relay = _add_same_relay(model, start)
    _add_coverage(model, start, intervals_all)
    _add_inter_runner_no_overlap(model, intervals_all, same_relay)
    relais_solo = _add_solo_constraints(model, same_relay)
    _add_no_solo_night(model, relais_solo, night_relay)
    _add_mandatory_pairs(model, same_relay)

    # Objectif : maximiser le nombre de relais en binômes
    model.maximize(sum(same_relay.values()))

    return _solve_and_save(model, start, same_relay, relais_solo, night_relay)


if __name__ == "__main__":
    build_and_solve()
