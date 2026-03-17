from dataclasses import dataclass
from collections import defaultdict


def count_by_size(relays: list[int]) -> dict[int, int]:
    counts = defaultdict(int)
    for s in relays:
        counts[s] += 1
    return dict(counts)


@dataclass
class RelayConstraints:
    """Snapshot des données du problème, passé au modèle CP-SAT."""

    # parcours
    total_km: float
    nb_segments: int
    speed_kmh: float
    start_hour: int

    # contraintes coureurs
    runners_data: dict
    compat_matrix: dict[tuple[str, str], int]
    binomes_pinned: list
    binomes_once_min: list
    binomes_once_max: list

    # contraintes planning
    min_relay_size: int
    solo_max_default: int
    solo_max_size: int
    nuit_max_default: int
    repos_jour_default: int
    repos_nuit_default: int

    # fonction objectif
    optimise_sur: str = 'compat_score'
    enable_flex: bool = True  # si False, tous les relais sont traités comme non-flexibles (size == req)

    @property
    def runners(self):
        return list(self.runners_data.keys())

    @property
    def relay_sizes(self):
        """Retourne les tailles nominales (nb_seg_requested) de chaque relais."""
        return {r: [req for req, _flex in cd.relais] for r, cd in self.runners_data.items()}

    @property
    def runner_nuit_max(self):
        return {r: cd.nuit_max for r, cd in self.runners_data.items()}

    @property
    def runner_solo_max(self):
        return {r: cd.solo_max for r, cd in self.runners_data.items()}

    @property
    def night_segments(self):
        return set(s for s in range(self.nb_segments) if self.is_night(s))

    @property
    def segment_km(self) -> float:
        """longueur d'un segment en km"""
        return self.total_km / self.nb_segments

    @property
    def segment_duration(self) -> float:
        """durée d'un segment en heures"""
        return self.segment_km / self.speed_kmh

    def segment_start_hour(self, seg: int) -> float:
        """Heure de début du segment (0-indexé), en heures depuis minuit mercredi."""
        return self.start_hour + seg * self.segment_duration

    def is_night(self, seg: int) -> bool:
        """Vrai si le segment démarre entre 0h et 6h (n'importe quel jour)."""
        h = self.segment_start_hour(seg) % 24
        return 0.0 <= h < 6.0

    def is_compatible(self, coureur_1: str, coureur_2: str) -> bool:
        """Retourne True si coureur_1 et coureur_2 peuvent former un binôme."""
        return self.compat_matrix.get((coureur_1, coureur_2), 0) > 0

    def compat_score(self, coureur_1: str, coureur_2: str) -> int:
        """Retourne le score de compatibilité (0, 1 ou 2)."""
        return self.compat_matrix.get((coureur_1, coureur_2), 0)

    def compute_upper_bound(self) -> int:
        """
        Calcule un majorant du nombre de binômes par relaxation LP.

        Variables : b[r1, r2, s] ∈ [0, min(count(r1,s), count(r2,s))]
        pour chaque paire compatible (r1 < r2) et taille s.

        Contraintes :
        (1) pour chaque coureur r et taille s : Σ_{r2} b[r,r2,s] ≤ count(r,s)
        (2) surplus exact : Σ_{r1,r2,s} s * b[r1,r2,s] = surplus

        Objectif : maximiser Σ b[r1,r2,s]
        """
        from ortools.linear_solver import pywraplp

        req_sizes = {r: [req for req, _flex in c.relais] for r, c in self.runners_data.items()}
        total_segs_engaged = sum(sum(sizes) for sizes in req_sizes.values())
        surplus = total_segs_engaged - self.nb_segments

        solver = pywraplp.Solver.CreateSolver("GLOP")

        counts = {r: count_by_size(sizes) for r, sizes in req_sizes.items()}
        all_sizes = sorted({s for sizes in req_sizes.values() for s in sizes})

        # Variables b[r1, r2, s] avec r1 < r2 (ordre de la liste runners)
        b = {}
        for s in all_sizes:
            for i, r1 in enumerate(self.runners):
                if counts[r1].get(s, 0) == 0:
                    continue
                for r2 in self.runners[i + 1 :]:
                    if counts[r2].get(s, 0) == 0:
                        continue
                    if not self.is_compatible(r1, r2):
                        continue
                    ub = min(counts[r1][s], counts[r2][s])
                    b[(r1, r2, s)] = solver.NumVar(0.0, ub, f"b_{r1}_{r2}_{s}")

        # Contrainte (1) : capacité par coureur et taille
        for r in self.runners:
            for s in all_sizes:
                c = counts[r].get(s, 0)
                if c == 0:
                    continue
                terms = [var for (r1, r2, sz), var in b.items() if sz == s and (r1 == r or r2 == r)]
                if terms:
                    ct = solver.Constraint(0.0, c)
                    for v in terms:
                        ct.SetCoefficient(v, 1.0)

        # Contrainte (2) : surplus exact
        ct_surplus = solver.Constraint(surplus, surplus)
        for (r1, r2, s), var in b.items():
            ct_surplus.SetCoefficient(var, float(s))

        obj = solver.Objective()
        for var in b.values():
            obj.SetCoefficient(var, 1.0)
        obj.SetMaximization()

        status = solver.Solve()
        if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
            print("LP infaisable ou non borné")
            return 0

        bound = solver.Objective().Value()

        # Solos par coureur : relais non appariés dans la solution LP
        # binomes_r[r][s] = Σ b[r,r2,s] (relais de r engagés en binôme pour la taille s)
        binomes_r: dict[str, dict[int, float]] = {r: defaultdict(float) for r in self.runners}
        for (r1, r2, s), var in b.items():
            v = var.solution_value()
            binomes_r[r1][s] += v
            binomes_r[r2][s] += v

        solo_km = {
            r: sum((counts[r].get(s, 0) - binomes_r[r][s]) * s * 5 for s in all_sizes)
            for r in self.runners
        }
        solo_nb = {
            r: sum(max(0.0, counts[r].get(s, 0) - binomes_r[r][s]) for s in all_sizes)
            for r in self.runners
        }
        total_solo_nb = sum(solo_nb.values())
        total_solo_km = sum(solo_km.values())

        # print(f"  Total segments engagés : {total_segs_engaged}  ({total_segs_engaged * 5} km)")
        # print(f"  Segments à couvrir     : {N_SEGMENTS}  ({N_SEGMENTS * 5} km)")
        # print(f"  Surplus                : {surplus} segments")
        print(f"\n  Majorant (relaxation LP) : {bound:.4f} → {int(bound)} binômes")
        print(f"  Solos (borne basse LP)   : {total_solo_nb:.2f} relais  ({total_solo_km:.0f} km)")
        return int(bound)

    def print_summary(self) -> None:
        """Affiche un résumé complet des données d'entrée du problème."""

        print("=" * 60)
        print("RÉSUMÉ DES DONNÉES D'ENTRÉE")
        print("=" * 60)
        print(
            f"  Parcours    : {self.total_km:.1f} km, {self.nb_segments} segments de {self.segment_km:.1f} km"
        )
        print(
            f"  Vitesse     : {self.speed_kmh} km/h → {self.segment_duration * 60:.1f} min/segment"
        )
        print(f"  Départ      : mercredi {self.start_hour}h00")
        print(f"  Repos jour  : {self.repos_jour_default} segments = {self.repos_jour_default * self.segment_duration:.1f}h")  # fmt: skip
        print(f"  Repos nuit  : {self.repos_nuit_default} segments = {self.repos_nuit_default * self.segment_duration:.1f}h")  # fmt: skip

        print()
        print("COUREURS")
        print("-" * 60)
        km_engages = 0
        for name, coureur in self.runners_data.items():
            req_sizes = [req for req, _flex in coureur.relais]
            km = sum(req_sizes) * self.segment_km
            km_engages += km
            flags = []
            if coureur.nuit_max == 0:
                flags.append("nuit interdit")
            elif coureur.nuit_max != self.nuit_max_default:
                flags.append(f"nuit_max={coureur.nuit_max}")
            if coureur.solo_max == 0:
                flags.append("solo interdit")
            elif coureur.solo_max != self.solo_max_default:
                flags.append(f"solo_max={coureur.solo_max}")
            if coureur.repos_jour != self.repos_jour_default:
                flags.append(f"repos_jour={coureur.repos_jour} segs ({coureur.repos_jour * self.segment_duration:.1f}h)")  # fmt: skip
            if coureur.repos_nuit != self.repos_nuit_default:
                flags.append(f"repos_nuit={coureur.repos_nuit} segs ({coureur.repos_nuit * self.segment_duration:.1f}h)")  # fmt: skip
            if coureur.dispo:
                flags.append("dispo partielle")
            if coureur.pinned_segments:
                flags.append(f"épinglé×{len(coureur.pinned_segments)}")
            flex_count = sum(1 for req, flex in coureur.relais if req != flex)
            if flex_count:
                flags.append(f"flex×{flex_count}")
            flag_str = f"  [{', '.join(flags)}]" if flags else ""
            sizes_str = " + ".join(
                f"{req * self.segment_km:.1f}" + (f"[±{flex * self.segment_km:.1f}]" if req != flex else "")
                for req, flex in coureur.relais
            )
            print(f"  {name:12s} : {km:.0f} km = {sizes_str} km{flag_str}")
        print(
            f"  {'TOTAL':12s}   {km_engages:.0f} km engagés  (reste {2 * self.total_km - km_engages:.1f} km en solo)"
        )
        self.compute_upper_bound()

        print()
        print("COMPATIBILITÉS (binômes possibles)")
        print("-" * 60)
        for name in self.runners:
            partners = sorted(r for r in self.runners if r != name and self.is_compatible(name, r))
            compat_str = ", ".join(partners) if partners else "— aucune"
            print(f"  {name:12s} : {compat_str}")
        if self.binomes_once_min:
            print(f"  1 relais min : {', '.join(f'{a}+{b}' for a, b in self.binomes_once_min)}")
        if self.binomes_once_max:
            print(f"  1 relais max : {', '.join(f'{a}+{b}' for a, b in self.binomes_once_max)}")

        # Vérifie que la matrice de compatibilité est symétrique
        asymmetries = [
            (a, b) for (a, b), v in self.compat_matrix.items() if v and not self.is_compatible(b, a)
        ]
        if asymmetries:
            print("AVERTISSEMENT : compatible n'est pas symétrique :")
            for a, b in asymmetries:
                print(f"  {a} → {b} mais pas l'inverse")

        print()
        print("DISPONIBILITÉS PARTIELLES")
        print("-" * 60)
        any_dispo = False
        for name, coureur in self.runners_data.items():
            if coureur.dispo:
                windows = ", ".join(f"[seg {s}–{e}]" for s, e in coureur.dispo)
                print(f"  {name:12s} : {windows}")
                any_dispo = True
        if not any_dispo:
            print("  (aucune)")

        print()
        print("RELAIS EPINGLÉS")
        print("-" * 60)
        if self.binomes_pinned:
            print("  Binômes :")
            for r1, r2, s, e in self.binomes_pinned:
                h_s = self.segment_start_hour(s)
                h_e = self.segment_start_hour(e)
                print(f"    {r1}+{r2} : segs [{s},{e}]  ({h_s:.1f}h–{h_e:.1f}h depuis départ)")
        else:
            print("  Binômes : (aucun)")
        pinned_runners = [(n, w) for n, c in self.runners_data.items() for w in c.pinned_segments]

        if pinned_runners:
            print("  Coureurs :")
            for name, w in pinned_runners:
                print(f"    {name} : segs {w}")
        else:
            print("  Coureurs : (aucun)")

        print("=" * 60)
