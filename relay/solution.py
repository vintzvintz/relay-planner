"""
relay/solution.py

Extraction, sérialisation et affichage d'une solution pour le modèle à points de passage.

API publique :
  Solution(relays, constraints)
    .from_cpsat(callback)                          -> classmethod
    .from_dict(data)                               -> classmethod
    .from_json(path)                               -> classmethod
    .to_dict() -> dict  {"constraints": ..., "relays": [...]}
    .to_json(filename)
    .save()
    .stats() -> SolutionStats
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .verifications import check

if TYPE_CHECKING:
    from .constraints import Constraints
    from .model import Model


@dataclass
class SolutionStats:
    score_duos: int           # somme des scores de compatibilité des binômes
    nb_duos: int              # nombre de relais en binôme (paires)
    nb_solo: int              # nombre de relais solo
    km_solo: float            # distance totale des relais solo (km)
    nb_pinned: int            # nombre de relais épinglés
    flex_plus: float          # somme des allongements (km > target) en km
    flex_moins: float         # somme des raccourcissements (km < target) en km
    score_dplus: float        # somme (D+ + D-) * lvl par coureur
    ub_score_target: int | None = None  # majorant score avec taille=target (heuristique, serré)
    ub_score_max: int | None = None     # majorant score avec taille=max_m (garanti)
    lb_solos: int | None = None         # borne basse solos (= n_solos de upper_bound target)


def _fill_rest_h(relays: list[dict]) -> None:
    """Calcule rest_h = repos réel (start[k+1] - end[k]) pour chaque relais."""
    by_runner: dict[str, list[dict]] = {}
    for rel in relays:
        by_runner.setdefault(rel["runner"], []).append(rel)
    for rels in by_runner.values():
        rels.sort(key=lambda r: r["time_start_min"])
        for i, rel in enumerate(rels):
            if i + 1 < len(rels):
                rel["rest_h"] = (rels[i + 1]["time_start_min"] - rel["time_end_min"]) / 60.0
            else:
                rel["rest_h"] = None


class Solution:
    """Solution extraite d'un callback CP-SAT pour le modèle waypoint."""

    def __init__(self, relays: list[dict], constraints: "Constraints"):
        self.relays = relays
        self.constraints = constraints

        if constraints is None:
            self.valid = None
        else:
            self.valid, buf = check(self)
            if not self.valid:
                print(buf.getvalue(), file=sys.stderr)


    @classmethod
    def from_cpsat(cls, callback) -> "Solution":
        """Extrait la solution depuis le callback CP-SAT."""
        model: Model = callback._relay_model
        c: Constraints = callback._constraints

        # Mapping index interne (avec points fictifs de pause) → index utilisateur.
        # Un point fictif (arc+1) partage l'index utilisateur du point réel suivant.
        pause_point_indices = {arc + 1 for arc in c.pause_arcs}
        internal_to_user: dict[int, int] = {}
        user_idx = 0
        for i in range(c.nb_points):
            if i in pause_point_indices:
                internal_to_user[i] = user_idx - 1  # même index que le point réel précédent
            else:
                internal_to_user[i] = user_idx
                user_idx += 1

        relays = []
        for r, coureur in c.runners_data.items():
            for k, spec in enumerate(coureur.relais):
                rk = (r, k)
                start_pt = callback.value(model.start[rk])
                end_pt = callback.value(model.end[rk])
                dist_m = callback.value(model.dist[rk])
                t_start = callback.value(model.time_start[rk])
                t_end = callback.value(model.time_end[rk])
                is_night = bool(callback.value(model.relais_nuit[rk])) if rk in model.relais_nuit else False
                is_solo = bool(callback.value(model.relais_solo[rk])) if rk in model.relais_solo else True

                # Repos minimum réglementaire
                if rk in model.repos_end:
                    repos_end_min = callback.value(model.repos_end[rk])
                    rest_min_h = (repos_end_min - t_end) / 60.0
                else:
                    rest_min_h = None

                # D+ / D-
                km_start = c.waypoints_km[start_pt]
                km_end = c.waypoints_km[end_pt]
                if c.parcours.has_profile:
                    # les variables CPSAT sont à jour seulement en mode optimisation d+/d-
                    d_plus, d_moins = c.parcours.denivele(km_start, km_end)
                else:
                    d_plus, d_moins = None, None

                # Partenaire
                partner = None
                for (r1, k1, r2, k2), bv in model.same_relay.items():
                    if callback.value(bv):
                        if (r1, k1) == rk:
                            partner = r2
                            break
                        if (r2, k2) == rk:
                            partner = r1
                            break

                wp_start = c.waypoints[start_pt]
                wp_end = c.waypoints[end_pt]
                relays.append({
                    "runner": r,
                    "k": k,
                    "start": start_pt,
                    "end": end_pt,
                    "wp_start": internal_to_user[start_pt],
                    "wp_end": internal_to_user[end_pt],
                    "km_start": c.waypoints_km[start_pt],
                    "km_end": c.waypoints_km[end_pt],
                    "lat_start": wp_start.get("lat"),
                    "lon_start": wp_start.get("lon"),
                    "alt_start": wp_start.get("alt"),
                    "lat_end": wp_end.get("lat"),
                    "lon_end": wp_end.get("lon"),
                    "alt_end": wp_end.get("alt"),
                    "km": dist_m / 1000.0,
                    "target_km": spec.target_m / 1000.0,
                    "time_start_min": t_start,
                    "time_end_min": t_end,
                    "solo": is_solo,
                    "night": is_night,
                    "partner": partner,
                    "pinned": (spec.pinned_start is not None or spec.pinned_end is not None),
                    **({"solo_forced": spec.solo} if spec.solo is not None else {}),
                    "rest_min_h": rest_min_h,
                    "d_plus": d_plus,
                    "d_moins": d_moins,
                })

        relays.sort(key=lambda r: (r["start"], r["runner"]))
        _fill_rest_h(relays)
        return cls(relays, c)

    @classmethod
    def from_dict(cls, data: dict) -> "Solution":
        from .constraints import Constraints
        constraints = Constraints.from_dict(data["constraints"])
        _fill_rest_h(data["relays"])
        sol = cls(data["relays"], constraints)
        return sol

    @classmethod
    def from_json(cls, path) -> "Solution":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    @classmethod
    def from_latest(cls) -> "tuple[Solution, str]":
        """Charge et retourne la solution la plus récente depuis PLANNING_DIR."""
        from ._dirs import latest_solution_path
        path = latest_solution_path()
        return cls.from_json(path), path

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def stats(self) -> SolutionStats:
        """Retourne les métriques clés de la solution."""
        c = self.constraints
        rl = self.relays

        score_duos = sum(
            c.compat_score(r["runner"], r["partner"])
            for r in rl
            if r["partner"] is not None
        ) // 2

        nb_duos = sum(1 for r in rl if r["partner"] is not None) // 2

        nb_solo = sum(1 for r in rl if r["solo"])
        km_solo = sum(r["km"] for r in rl if r["solo"])

        nb_pinned = sum(1 for r in rl if r.get("pinned"))

        flex_plus  = sum(r["km"] - r["target_km"] for r in rl if r["km"] > r["target_km"])
        flex_moins = sum(r["target_km"] - r["km"] for r in rl if r["km"] < r["target_km"])

        score_dplus = 0.0
        if (cd := c.cumul_dplus) is not None:
            cumul_dp, cumul_dm = cd
            for r in rl:
                runner_data = c.runners_data.get(r["runner"])
                lvl = (runner_data.options.lvl or 0) if runner_data else 0
                if not lvl:
                    continue
                s, e = r["start"], r["end"]
                score_dplus += (cumul_dp[e] - cumul_dp[s] + cumul_dm[e] - cumul_dm[s]) * lvl

        ub_target = c.upper_bound
        ub_max = c.upper_bound_max

        return SolutionStats(
            score_duos=score_duos,
            nb_duos=nb_duos,
            nb_solo=nb_solo,
            km_solo=km_solo,
            nb_pinned=nb_pinned,
            flex_plus=flex_plus,
            flex_moins=flex_moins,
            score_dplus=score_dplus,
            ub_score_target=ub_target.score if ub_target is not None else None,
            ub_score_max=ub_max.score if ub_max is not None else None,
            lb_solos=ub_target.n_solos if ub_target is not None else None,
        )

    def to_dict(self) -> dict:
        """Retourne la solution sous forme de dict sérialisable (contraintes + relais)."""
        return {
            "constraints": self.constraints.to_dict(),
            "relays": self.relays,
        }

    def to_json(self, filename):
        """Sauvegarde la solution en JSON."""
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    def to_text(self) -> str:
        """Retourne le planning complet en texte."""
        from .formatters.text import to_text
        return to_text(self)


    def save(self, *, base, as_json=True, csv=True, html=True, txt=True, gpx=True, kml=False, split=True):
        """Sauvegarde la solution dans les formats demandés (JSON, CSV, HTML, texte, GPX/KML).

        Paramètres :
          base — chemin de base sans extension (généré une fois par résolution, partagé entre solutions)
        Paramètres optionnels (tous True par défaut) :
          as_json, csv, html, txt — formats texte
          gpx — GPX + KML (ignoré si parcours_gpx n'est pas défini)
          split — exporter des fichiers GPX/KML individuels dans PLANNING_DIR/base/<coureur>/*.gpx
        """
        Path(base).parent.mkdir(parents=True, exist_ok=True)
        if as_json:
            self.to_json(f"{base}.json")
        if csv:
            from .formatters.commun import to_csv
            to_csv(self, f"{base}.csv")
        if html:
            from .formatters.html import to_html
            with open(f"{base}.html", "w", encoding="utf-8") as f:
                f.write(to_html(self))
        if txt:
            with open(f"{base}.txt", "w", encoding="utf-8") as f:
                f.write(self.to_text())

        gpx_src = self.constraints.parcours.gpx_path
        if gpx_src:
            from .formatters.gpx import to_gpx, to_kml, to_split
            if gpx:
                to_gpx(self, gpx_src, f"{base}.gpx")
            if kml:
                to_kml(self, gpx_src, f"{base}.kml")
            if split:
                to_split(self, gpx_src, Path(base).parent / "split", gpx, kml)

        self.print_summary(suffix=f"--> {Path(base).name}")

    def print_summary(self, suffix: str = "") -> None:
        """Affiche un résumé compact de la solution sur stdout."""
        s = self.stats()

        ub_str = ""
        if s.ub_score_target is not None:
            ub_str = f"≤{s.ub_score_target}]" 

        solo_str = ""
        if s.lb_solos is not None:
            solo_str=f"{s.nb_solo} [≥{s.lb_solos}]"
        else:
            solo_str = f"{s.nb_solo}"

        suffix_str = f"  {suffix}" if suffix else ""
        print(
            f"✅ Solution  "
            f"duos: {s.score_duos} [{ub_str}] "
            f"solos:{solo_str} ({s.km_solo:.1f} km) "
            f"flex:+{s.flex_plus:.1f}/-{s.flex_moins:.1f}km "
            f"score_dplus:{s.score_dplus:.0f} "
            f"{suffix_str}"
        )

