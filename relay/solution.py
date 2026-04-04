"""
Solution CP-SAT : données, vérification et sérialisation.

API publique :
  Solution(relays, constraints, solver_score=None, skip_validation=False)
    .from_cpsat(solver)                           -> classmethod
    .from_dict(data, skip_validation=False)       -> classmethod
    .from_json(path, skip_validation=False)       -> classmethod
    .to_dict() -> dict  {"constraints": ..., "relays": [...]}
    .to_text() -> str
    .to_csv(filename)
    .to_json(filename)
    .to_html(filename)
    .save()
    .stats() -> (score, n_binomes, n_solos, km_solos, n_flex, n_pinned, km_flex)
"""

import io
import json
import os
import sys
from datetime import datetime

from . import verifications as verif
from . import formatters
from .model import BINOME_WEIGHT

OUTDIR = "plannings"


class Solution:
    """Encapsule une solution CP-SAT avec contraintes, vérification et formatage."""

    def __init__(self, relays: list, constraints, solver_score=None, skip_validation=False):
        self.constraints = constraints
        self.solver_score = solver_score
        self.relays = relays
        if constraints is None or skip_validation:
            self.valid = None
        else:
            buf = io.StringIO()
            self.valid = verif.check(self, out=buf)
            if not self.valid:
                print(buf.getvalue(), file=sys.stderr)

    @classmethod
    def from_cpsat(cls, solver):
        """Construit une Solution à partir de l'état courant du solveur CP-SAT."""
        model = solver._relay_model
        c = solver._constraints
        segment_km = c.segment_km
        relais_raw = []
        for r in c.runners:
            for k, spec in enumerate(c.runners_data[r].relais):
                sz_declared = max(spec.size)
                s = solver.value(model.start[r][k])
                e = solver.value(model.end[r][k])
                sz = solver.value(model.size[r][k])
                partner = None
                for key, bv in model.same_relay.items():
                    if solver.value(bv) == 1:
                        if key[0] == r and key[1] == k:
                            partner = key[2]
                        elif key[2] == r and key[3] == k:
                            partner = key[0]
                km_deb = c.time_seg_to_active(s) * c.segment_km
                km_fin = c.time_seg_to_active(e) * c.segment_km
                profil = c.profil
                if profil is not None:
                    d_plus, d_moins = profil.denivele(km_deb, km_fin)
                else:
                    d_plus, d_moins = None, None
                night_relay = bool(solver.value(model.relais_nuit[r][k]))
                opts = c.runners_data[r].options
                rest_min_segs = opts.repos_nuit if night_relay else opts.repos_jour
                relais_raw.append({
                    "runner":        r,
                    "k":             k,
                    "start":         s,
                    "end":           e,
                    "size":          sz,
                    "size_decl":     sz_declared,
                    "km":            sz * segment_km,
                    "flex":          sz < sz_declared,
                    "solo":          bool(solver.value(model.relais_solo[r][k])),
                    "night":         night_relay,
                    "partner":       partner,
                    "pinned":        spec.pinned,
                    "rest_h":        None,
                    "rest_min_segs": rest_min_segs,
                    "d_plus":        d_plus,
                    "d_moins":       d_moins,
                })
        relais_raw.sort(key=lambda x: (x["start"], x["runner"]))

        by_runner = {}
        for rel in relais_raw:
            by_runner.setdefault(rel["runner"], []).append(rel)
        for r_rels in by_runner.values():
            r_rels.sort(key=lambda x: x["start"])
            for i, rel in enumerate(r_rels):
                if i < len(r_rels) - 1:
                    rel["rest_h"] = (r_rels[i + 1]["start"] - rel["end"]) * c.segment_duration

        return cls(relais_raw, c, solver_score=solver.objective_value)

    @classmethod
    def from_dict(cls, data: dict, skip_validation=False):
        """Construit une Solution depuis un dict produit par to_dict()."""
        from .constraints import Constraints
        constraints = Constraints.from_dict(data["constraints"])
        return cls(data["relays"], constraints, skip_validation=skip_validation)

    @classmethod
    def from_json(cls, path, skip_validation=False):
        """Charge une Solution depuis un fichier JSON produit par to_json()."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data, skip_validation=skip_validation)

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def stats(self):
        """Retourne (score, n_binomes, n_solos, km_solos, n_flex, n_pinned, km_flex).

        Le score est calculé comme BINOME_WEIGHT * somme compat_score moins
        pénalité flex.

        ATTENTION : la formule du score est dupliquée en quatre endroits — tout
        changement doit être répercuté simultanément dans :
          - relay/model.py       : _objective_expr()      (fonction objectif CP-SAT)
          - relay/upper_bound.py : _compute_upper_bound_glop()  (relaxation LP GLOP)
          - relay/upper_bound.py : _compute_upper_bound_cpsat() (majorant CP-SAT)
          - relay/solution.py    : Solution.stats()              (recalcul post-solve)
        """
        c = self.constraints
        rl = self.relays
        n_binomes = sum(1 for x in rl if x["partner"]) // 2
        solos = [x for x in rl if x["solo"]]
        n_flex = sum(1 for x in rl if x["flex"])
        n_pinned = sum(1 for x in rl if x["pinned"] is not None)
        km_flex = sum((x["size_decl"] - x["size"]) * c.segment_km for x in rl if x["flex"])
        if c is not None:
            binome_score = sum(
                c.compat_score(r["runner"], r["partner"])
                for r in rl
                if r["partner"] is not None
            ) // 2  # chaque binôme apparaît deux fois (un par coureur)
            flex_penalty = sum(
                r["size_decl"] - r["size"] for r in rl if r["flex"]
            )
            score = BINOME_WEIGHT * binome_score - flex_penalty
        else:
            score = None
        return score, n_binomes, len(solos), sum(x["km"] for x in solos), n_flex, n_pinned, km_flex

    def to_text(self) -> str:
        """Retourne le planning complet en texte (planning chrono + récap)."""
        return formatters.to_text(self)

    def to_html(self, filename):
        """Sauvegarde le planning en HTML (Gantt + planning détaillé)."""
        with open(filename, "w", encoding="utf-8") as f:
            f.write(formatters.to_html(self))

    def to_csv(self, filename):
        """Sauvegarde la solution en CSV (format lisible)."""
        formatters.to_csv(self, filename)

    def to_dict(self) -> dict:
        """Retourne la solution sous forme de dict sérialisable (contraintes + relais)."""
        return {
            "constraints": self.constraints.to_dict(),
            "relays": self.relays,
        }

    def to_json(self, filename):
        """Sauvegarde la solution en JSON (format interne)."""
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    def save(self):
        """Affiche la solution et la sauvegarde dans des fichiers horodatés."""
        outdir = OUTDIR
        os.makedirs(outdir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        text = self.to_text()

        txt_fname = os.path.join(outdir, f"planning_{ts}.txt")
        with open(txt_fname, "w", encoding="utf-8") as f:
            f.write(text)

        csv_fname = os.path.join(outdir, f"planning_{ts}.csv")
        self.to_csv(csv_fname)

        json_fname = os.path.join(outdir, f"planning_{ts}.json")
        self.to_json(json_fname)

        html_fname = os.path.join(outdir, f"planning_{ts}.html")
        self.to_html(html_fname)

        if self.constraints.parcours_gpx:
            from relay.gpx import solution_to_gpx, solution_to_kml
            gpx_fname = os.path.join(outdir, f"planning_{ts}.gpx")
            solution_to_gpx(self, self.constraints.parcours_gpx, gpx_fname)
            # kml_fname = os.path.join(outdir, f"planning_{ts}.kml")
            # solution_to_kml(self, self.constraints.parcours_gpx, kml_fname)

        score, n_binomes, n_solo, km_solo, n_flex, n_pinned, km_flex = self.stats()
        km_flex_str = f" ({km_flex:.1f} km)" if km_flex else ""
        print(f"score:{score} binomes:{n_binomes} solos:{n_solo} ({km_solo:.1f} km) flex:{n_flex}{km_flex_str} pinned:{n_pinned}  --> planning_{ts}")
