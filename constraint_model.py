"""
Construction du modèle CP-SAT — relais Lyon-Fessenheim.

Ce module expose :
- build_model() : construit et retourne le modèle avec toutes les contraintes
- build_model_fixed_config() : idem, avec les binômes fixés à une configuration donnée
"""

from ortools.sat.python import cp_model
from data import (
    N_SEGMENTS,
    RUNNER_RELAYS,
    PARTIAL_AVAILABILITY,
    REST_NORMAL,
    REST_NIGHT,
    NIGHT_SEGMENTS,
    PINNED_BINOMES,
    PINNED_RUNNERS,
    COMPATIBLE,
    MANDATORY_PAIRS,
    MULTI_NIGHT_ALLOWED,
    check_compatible_symmetric,
)

check_compatible_symmetric()

RUNNERS = list(RUNNER_RELAYS.keys())
N_RUNNERS = len(RUNNERS)
SEG_NIGHT_LIST = sorted(NIGHT_SEGMENTS)


def _add_variables(model):
    """Crée les variables start/end et intervalles pour chaque relais."""
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
    """Crée les variables night_relay[r][k] et applique la contrainte au plus 1 nuit."""
    night_relay = {}
    for r in RUNNERS:
        night_relay[r] = []
        for k, sz in enumerate(RUNNER_RELAYS[r]):
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
    """Repos minimum entre toute paire de relais d'un même coureur."""
    for r in RUNNERS:
        n_relays = len(RUNNER_RELAYS[r])
        if n_relays < 2:
            continue
        for k in range(n_relays):
            for kp in range(k + 1, n_relays):
                k_before_kp = model.new_bool_var(f"bef_{r}_{k}_{kp}")
                k_day_then_kp = model.new_bool_var(f"bkd_{r}_{k}_{kp}")
                k_night_then_kp = model.new_bool_var(f"bkn_{r}_{k}_{kp}")
                model.add_bool_and([k_before_kp, ~night_relay[r][k]]).only_enforce_if(k_day_then_kp)
                model.add_bool_or([~k_before_kp, night_relay[r][k]]).only_enforce_if(~k_day_then_kp)
                model.add_bool_and([k_before_kp, night_relay[r][k]]).only_enforce_if(k_night_then_kp)
                model.add_bool_or([~k_before_kp, ~night_relay[r][k]]).only_enforce_if(~k_night_then_kp)
                model.add(end[r][k] + REST_NORMAL <= start[r][kp]).only_enforce_if(k_day_then_kp)
                model.add(end[r][k] + REST_NIGHT <= start[r][kp]).only_enforce_if(k_night_then_kp)
                kp_day_then_k = model.new_bool_var(f"bkpd_{r}_{k}_{kp}")
                kp_night_then_k = model.new_bool_var(f"bkpn_{r}_{k}_{kp}")
                model.add_bool_and([~k_before_kp, ~night_relay[r][kp]]).only_enforce_if(kp_day_then_k)
                model.add_bool_or([k_before_kp, night_relay[r][kp]]).only_enforce_if(~kp_day_then_k)
                model.add_bool_and([~k_before_kp, night_relay[r][kp]]).only_enforce_if(kp_night_then_k)
                model.add_bool_or([k_before_kp, ~night_relay[r][kp]]).only_enforce_if(~kp_night_then_k)
                model.add(end[r][kp] + REST_NORMAL <= start[r][k]).only_enforce_if(kp_day_then_k)
                model.add(end[r][kp] + REST_NIGHT <= start[r][k]).only_enforce_if(kp_night_then_k)


def _add_availability(model, start, end):
    """Applique les disponibilités partielles et affectations fixes (Olivier/Alexis)."""
    for r, windows in PARTIAL_AVAILABILITY.items():
        n_relays = len(RUNNER_RELAYS[r])
        for k in range(n_relays):
            # start[r][k] must fall within one of the availability windows
            window_bools = []
            for i, (avail_start, avail_end) in enumerate(windows):
                b = model.new_bool_var(f"avail_{r}_{k}_{i}")
                model.add(start[r][k] >= avail_start).only_enforce_if(b)
                model.add(end[r][k] <= avail_end).only_enforce_if(b)
                window_bools.append(b)
            model.add_bool_or(window_bools)

    # Pinned binômes: force a pair to share a relay covering the window.
    pair_relay_counters = {}
    for (r1, r2), window in PINNED_BINOMES:
        pair_key = (r1, r2)
        idx = pair_relay_counters.get(pair_key, 0)
        window_start, window_end = window[0], window[1]
        min_relay_size = window_end - window_start

        r1_relays = [k for k, sz in enumerate(RUNNER_RELAYS[r1]) if sz >= min_relay_size]
        r2_relays = [k for k, sz in enumerate(RUNNER_RELAYS[r2]) if sz >= min_relay_size]
        if idx < len(r1_relays) and idx < len(r2_relays):
            k1, k2 = r1_relays[idx], r2_relays[idx]
            sz1 = RUNNER_RELAYS[r1][k1]
            model.add(start[r1][k1] <= window_start)
            model.add(start[r1][k1] >= window_end - sz1)
            model.add(start[r2][k2] == start[r1][k1])
        pair_relay_counters[pair_key] = idx + 1

    # Pinned runners: force a single runner to have a relay covering the window.
    runner_relay_counters = {}
    for r, window in PINNED_RUNNERS:
        idx = runner_relay_counters.get(r, 0)
        window_start, window_end = window[0], window[1]
        min_relay_size = window_end - window_start

        r_relays = [k for k, sz in enumerate(RUNNER_RELAYS[r]) if sz >= min_relay_size]
        if idx < len(r_relays):
            k = r_relays[idx]
            sz = RUNNER_RELAYS[r][k]
            model.add(start[r][k] <= window_start)
            model.add(start[r][k] >= window_end - sz)
        runner_relay_counters[r] = idx + 1


def _add_same_relay(model, start):
    """Crée les variables same_relay pour les binômes potentiels."""
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
                    no_overlap_dom = cp_model.Domain(-N_SEGMENTS, -sz_r).union_with(
                        cp_model.Domain(sz_r, N_SEGMENTS)
                    )
                    model.add_linear_expression_in_domain(
                        diff, no_overlap_dom
                    ).only_enforce_if(~b)
    return same_relay


def _add_coverage(model, start, intervals_all):
    """Contrainte de couverture : chaque segment couvert par 1 ou 2 relais."""
    all_ivs = [iv for _, _, _, iv in intervals_all]
    all_demand = [1 for _ in intervals_all]
    model.add_cumulative(all_ivs, all_demand, 2)

    for s in range(N_SEGMENTS):
        covers_s = []
        for r in RUNNERS:
            for k, sz in enumerate(RUNNER_RELAYS[r]):
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
    """Force la disjonction entre relais de coureurs différents non binômables."""
    for ri, r in enumerate(RUNNERS):
        for k, _ in enumerate(RUNNER_RELAYS[r]):
            iv_rk = intervals_all[
                [i for i, (rr, kk, _, _) in enumerate(intervals_all) if rr == r and kk == k][0]
            ][3]
            for rpi in range(ri + 1, N_RUNNERS):
                rp = RUNNERS[rpi]
                for kp, _ in enumerate(RUNNER_RELAYS[rp]):
                    iv_rpkp = intervals_all[
                        [i for i, (rr, kk, _, _) in enumerate(intervals_all) if rr == rp and kk == kp][0]
                    ][3]
                    key = (r, k, rp, kp)
                    key_rev = (rp, kp, r, k)
                    if key in same_relay or key_rev in same_relay:
                        continue
                    model.add_no_overlap([iv_rk, iv_rpkp])


def _add_solo_constraints(model, same_relay):
    """Crée relais_solo[r][k] et limite à au plus 1 solo par coureur."""
    relais_solo = {}
    for r in RUNNERS:
        relais_solo[r] = []
        for k in range(len(RUNNER_RELAYS[r])):
            partners = [
                bv
                for key, bv in same_relay.items()
                if (key[0] == r and key[1] == k) or (key[2] == r and key[3] == k)
            ]
            b = model.new_bool_var(f"solo_{r}_{k}")
            if partners:
                model.add_bool_or(partners).only_enforce_if(~b)
                model.add_bool_and([~p for p in partners]).only_enforce_if(b)
            else:
                model.add(b == 1)
            relais_solo[r].append(b)

    for r in RUNNERS:
        model.add(sum(relais_solo[r]) <= 1)

    return relais_solo


def _add_no_solo_night(model, relais_solo, night_relay):
    """Interdit les relais solo la nuit."""
    for r in RUNNERS:
        for k in range(len(RUNNER_RELAYS[r])):
            model.add(relais_solo[r][k] + night_relay[r][k] <= 1)


def _add_mandatory_pairs(model, same_relay):
    """Impose au moins un relais en binôme pour chaque paire obligatoire."""
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


def build_model():
    """Construit le modèle CP-SAT avec toutes les contraintes (sans objectif).

    Retourne (model, start, same_relay, relais_solo, night_relay).
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
    return model, start, same_relay, relais_solo, night_relay


def build_model_fixed_config(active_keys, optimal_score):
    """Construit le modèle avec les binômes fixés à la configuration donnée.

    active_keys : frozenset de clés same_relay devant valoir 1.
    optimal_score : valeur cible de la somme des same_relay.
    """
    model, start, same_relay, relais_solo, night_relay = build_model()

    for key, bv in same_relay.items():
        if key in active_keys:
            model.add(bv == 1)
        else:
            model.add(bv == 0)

    model.add(sum(same_relay.values()) == optimal_score)
    return model, start, same_relay, relais_solo, night_relay
