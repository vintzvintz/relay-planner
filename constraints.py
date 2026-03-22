from dataclasses import dataclass
from collections import defaultdict
import math

# Noms des types de relais (clés du dict relay_types de RelayConstraints)
R10   = "R10"
R15   = "R15"
R20   = "R20"
R30   = "R30"
R13_F = "R13_F"
R15_F = "R15_F"


def make_relay_types(nb_segments: int, total_km: float, enable_flex: bool) -> dict:
    """
    Retourne un dict de types de relais pour le nombre de segments donné.

    Tailles nominales (en km) :
      R10 = 10 km, R15 = 15 km, R20 = 20 km, R30 = 30 km
      R13_F = R10..R13 km (flex), R15_F = R10..R15 km (flex)
    """
    seg_km = total_km / nb_segments

    # calcul empirique du nombre de segment pour chaque type de relais.
    r10 = round(10 / seg_km)
    r13 = math.floor(13.9 / seg_km)
    r15 = math.ceil(14.5 / seg_km)    # pas moins de 14,5km
    r20 = round(20 / seg_km)
    r30 = math.floor(30 / seg_km)   # pas plus de 30km

    s10 = {r10}
    s15 = {r15}
    s20 = {r20}
    s30 = {r30}

    if enable_flex:
        s13_f = set(range(r10, r13 + 1))
        s15_f = set(range(r10, r15 + 1))
    else:
        s13_f = {r13}
        s15_f = {r15}

    return {R10: s10, R15: s15, R20: s20, R30: s30, R13_F: s13_f, R15_F: s15_f}


@dataclass
class RelaySpec:
    """Descripteur complet d'un relais pour un coureur.

    size        : tailles permises en segments (singleton = fixe, multi = flexible).
    paired_with : (runner_name, relay_index) du relais partenaire, positionné via SharedRelay.
    window      : le relais doit être entièrement inclus dans [start, end] (segments, inclus).
    pinned      : segment de départ fixé. Incompatible avec flex (len(size) > 1).
    """
    size: set[int]
    paired_with: tuple[str, int] | None = None  # (runner_name, relay_index)
    window: list[tuple[int, int]] | None = None  # liste d'intervalles [start, end] inclus
    pinned: int | None = None


class RelayHandle:
    """Référence interne à un relais spécifique d'un coureur.

    Utilisé par SharedRelay pour enregistrer les pairings via _pair_with().
    """

    def __init__(self, runner_name: str, relay_index: int, spec: "RelaySpec"):
        self.runner_name = runner_name
        self.relay_index = relay_index
        self._spec = spec

    def _pair_with(self, other: "RelayHandle") -> None:
        self._spec.paired_with = (other.runner_name, other.relay_index)
        other._spec.paired_with = (self.runner_name, self.relay_index)


class SharedRelay:
    """Relais partagé entre plusieurs coureurs, créé via RelayConstraints.new_relay().

    Passer la même instance à add_relay() de plusieurs coureurs les apparie automatiquement.
    Limité à 2 coureurs (un binôme).
    """

    def __init__(self, size: set[int]):
        self.size = size
        self._handles: list[RelayHandle] = []

    def _register(self, handle: RelayHandle) -> None:
        if len(self._handles) >= 2:
            raise ValueError("Un SharedRelay ne peut être partagé qu'entre 2 coureurs.")
        for existing in self._handles:
            handle._pair_with(existing)
        self._handles.append(handle)


@dataclass
class Coureur:
    """Contraintes sur chaque coureur avec valeurs par défaut.

    relais : liste de RelaySpec, un par relais.
      Chaque RelaySpec encode la taille, l'éventuel partenaire, la fenêtre de placement,
      et le départ fixé (pinned).
    """
    relais: list[RelaySpec]
    repos_jour: int | None = None         # None = utilise repos_jour_default du RelayConstraints
    repos_nuit: int | None = None         # None = utilise repos_nuit_default du RelayConstraints
    solo_max: int | None = None           # None = utilise solo_max_default du RelayConstraints
    nuit_max: int | None = None           # None = utilise nuit_max_default du RelayConstraints
    max_same_partenaire: int | None = None  # None = utilise max_same_partenaire_default


@dataclass
class RelayIntervals:
    """Abstraction d'une ou plusieurs plages de segments.

    Utilisée pour définir les contraintes de placement (window) et les dispos coureurs.
    Chaque tuple (start, end) est un intervalle de segments [start, end] inclus.
    """
    intervals: list[tuple[int, int]]



def count_by_size(relays: list[int]) -> dict[int, int]:
    counts = defaultdict(int)
    for s in relays:
        counts[s] += 1
    return dict(counts)


class RunnerBuilder:
    """Builder fluide pour déclarer les relais d'un coureur.

    Créé via RelayConstraints.new_runner(). Les appels à add_relay() accumulent
    des RelaySpec dans le Coureur interne, qui est enregistré dans runners_data.
    """

    def __init__(self, name: str, coureur: Coureur, constraints: "RelayConstraints"):
        self.name = name
        self._coureur = coureur
        self._constraints = constraints

    def set_options(
        self,
        *,
        solo_max: int | None = None,
        nuit_max: int | None = None,
        repos_jour: float | None = None,
        repos_nuit: float | None = None,
        max_same_partenaire: int | None = None,
    ) -> "RunnerBuilder":
        """Surcharge les options individuelles du coureur (remplace les kwargs de new_runner)."""
        if solo_max is not None:
            self._coureur.solo_max = solo_max
        if nuit_max is not None:
            self._coureur.nuit_max = nuit_max
        if repos_jour is not None:
            self._coureur.repos_jour = self._constraints.duration_to_segs(repos_jour)
        if repos_nuit is not None:
            self._coureur.repos_nuit = self._constraints.duration_to_segs(repos_nuit)
        if max_same_partenaire is not None:
            self._coureur.max_same_partenaire = max_same_partenaire
        return self

    def add_relay(
        self,
        size: "str | SharedRelay",
        *,
        nb: int = 1,
        window: "RelayIntervals | tuple[int, int] | None" = None,
        pinned: int | None = None,
    ) -> "RunnerBuilder":
        """Ajoute nb relais identiques au coureur et retourne self pour le chaînage.

        size : nom de type (str) ou SharedRelay (créé via constraints.new_relay()).
               Pour un SharedRelay, nb est ignoré.
        """
        if not isinstance(size, (str, SharedRelay)):
            raise TypeError(f"size doit être un nom de type (str) ou un SharedRelay, pas {type(size).__name__}.")

        window_list: list[tuple[int, int]] | None = None
        if isinstance(window, RelayIntervals):
            window_list = window.intervals
        elif isinstance(window, tuple):
            window_list = [window]

        if isinstance(size, str):
            size = self._constraints.relay_types[size]

        if isinstance(size, SharedRelay):
            if nb != 1:
                raise ValueError("nb>1 n'est pas compatible avec un SharedRelay.")
            idx = len(self._coureur.relais)
            spec = RelaySpec(size=size.size, window=window_list, pinned=pinned)
            self._coureur.relais.append(spec)
            size._register(RelayHandle(self.name, idx, spec))
            return self

        for _ in range(nb):
            self._coureur.relais.append(RelaySpec(size=size, window=window_list, pinned=pinned))
        return self



class RelayConstraints:
    """Snapshot des données du problème, passé au modèle CP-SAT."""

    def __init__(
        self,
        total_km: float,
        nb_segments: int,
        speed_kmh: float,
        start_hour: float,
        compat_matrix: dict[tuple[str, str], int],
        solo_max_km: float,
        solo_max_default: int,
        nuit_max_default: int,
        repos_jour_heures: float,
        repos_nuit_heures: float,
        nuit_debut: float = 0.0,
        nuit_fin: float = 6.0,
        max_same_partenaire: int | None = None,
        enable_flex: bool = True,
        allow_flex_flex: bool = True,
    ):
        self.total_km = total_km
        self.nb_segments = nb_segments
        self.speed_kmh = speed_kmh
        self.start_hour = start_hour
        # Déplie le triangle inférieur en matrice symétrique complète
        self.compat_matrix: dict[tuple[str, str], int] = {
            **compat_matrix,
            **{(b, a): v for (a, b), v in compat_matrix.items()},
        }
        self.solo_max_size = int(solo_max_km * nb_segments / total_km)
        self.solo_max_default = solo_max_default
        self.nuit_max_default = nuit_max_default
        self.nuit_debut = nuit_debut
        self.nuit_fin = nuit_fin
        self.repos_jour_default: int = self.duration_to_segs(repos_jour_heures)
        self.repos_nuit_default: int = self.duration_to_segs(repos_nuit_heures)

        self.runners_data: dict[str, Coureur] = {}
        self.once_max: list[tuple[str, str, int]] = []
        self.max_same_partenaire: int | None = max_same_partenaire
        self.relay_types: dict[str, set[int]] = make_relay_types(nb_segments, total_km, enable_flex)
        self.allow_flex_flex: bool = allow_flex_flex

        # Index des coureurs connus (pour validation dans new_runner)
        self._known_runners: set[str] = {name for pair in self.compat_matrix for name in pair}

        # Résultats de la relaxation LP (remplis à la première demande via lp_bounds)
        self._lp_computed: bool = False
        self.lp_upper_bound: int | None = None
        self.lp_upper_bound_exact: float | None = None
        self.lp_solo_nb: float | None = None
        self.lp_solo_km: float | None = None

    # ------------------------------------------------------------------
    # API déclarative
    # ------------------------------------------------------------------

    def new_runner(self, name: str) -> RunnerBuilder:
        """Crée un nouveau coureur et retourne son RunnerBuilder."""
        if name not in self._known_runners:
            raise ValueError(f"Coureur '{name}' absent de la matrice de compatibilité")
        coureur = Coureur(relais=[])
        self.runners_data[name] = coureur
        return RunnerBuilder(name, coureur, self)

    def add_max_binomes(self, runner1: "RunnerBuilder", runner2: "RunnerBuilder", nb: int) -> None:
        """Limite à au plus nb binômes entre runner1 et runner2 sur tout le planning."""
        self.once_max.append((runner1.name, runner2.name, nb))

    def new_relay(
        self,
        size: str,
    ) -> SharedRelay:
        """Crée un relais partagé à passer à add_relay() de deux coureurs pour les apparier."""
        if not isinstance(size, str):
            raise TypeError(f"size doit être un nom de type (str), pas {type(size).__name__}.")
        return SharedRelay(size=self.relay_types[size])

    def night_windows(self) -> RelayIntervals:
        """Retourne un RelayIntervals couvrant toutes les plages nocturnes (0h–6h)."""
        intervals: list[tuple[int, int]] = []
        in_night = False
        seg_start = 0
        for s in range(self.nb_segments):
            if self.is_night(s):
                if not in_night:
                    seg_start = s
                    in_night = True
            else:
                if in_night:
                    intervals.append((seg_start, s - 1))
                    in_night = False
        if in_night:
            intervals.append((seg_start, self.nb_segments - 1))
        return RelayIntervals(intervals)

    # ------------------------------------------------------------------
    # Propriétés et méthodes utilitaires
    # ------------------------------------------------------------------

    @property
    def paired_relays(self) -> list[tuple[str, int, str, int]]:
        """Tuples (r1, k1, r2, k2) pour tous les pairings déclarés via SharedRelay."""
        seen: set[frozenset] = set()
        result = []
        for r, coureur in self.runners_data.items():
            for k, spec in enumerate(coureur.relais):
                if spec.paired_with is not None:
                    r2, k2 = spec.paired_with
                    key = frozenset({(r, k), (r2, k2)})
                    if key not in seen:
                        seen.add(key)
                        result.append((r, k, r2, k2))
        return result

    @property
    def runners(self):
        return list(self.runners_data.keys())

    @property
    def relay_sizes(self):
        """Retourne les tailles nominales (max du set) de chaque relais."""
        return {r: [max(spec.size) for spec in cd.relais] for r, cd in self.runners_data.items()}

    @property
    def runner_nuit_max(self):
        return {r: self._resolved_nuit_max(cd) for r, cd in self.runners_data.items()}

    @property
    def runner_solo_max(self):
        return {r: self._resolved_solo_max(cd) for r, cd in self.runners_data.items()}

    @property
    def runner_repos_jour(self):
        return {r: self._resolved_repos_jour(cd) for r, cd in self.runners_data.items()}

    @property
    def runner_repos_nuit(self):
        return {r: self._resolved_repos_nuit(cd) for r, cd in self.runners_data.items()}

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
        """Vrai si le segment démarre entre nuit_debut et nuit_fin (n'importe quel jour)."""
        h = self.segment_start_hour(seg) % 24
        if self.nuit_debut <= self.nuit_fin:
            return self.nuit_debut <= h < self.nuit_fin
        else:
            return h >= self.nuit_debut or h < self.nuit_fin

    def duration_to_segs(self, hours: float) -> int:
        """Convertit une durée en heures en nombre de segments (arrondi au supérieur)."""
        return math.ceil(hours * self.speed_kmh * self.nb_segments / self.total_km)

    def size_of(self, relay_name: str) -> int:
        """Retourne la taille en segments du type de relais donné.

        Lève ValueError si le type est flexible (plusieurs tailles possibles).
        """
        sizes = self.relay_types[relay_name]
        if len(sizes) != 1:
            raise ValueError(
                f"Le type '{relay_name}' est flexible ({sorted(sizes)} segs) : utilisez relay_types[relay_name] directement."
            )
        return next(iter(sizes))

    def km_to_seg(self, km: float) -> int:
        """Convertit une distance en km en numéro de segment (arrondi au supérieur)."""
        return math.floor(km * self.nb_segments / self.total_km)

    def hour_to_seg(self, hour: float, jour: int = 0) -> int:
        """Convertit une heure absolue (+ décalage en jours) en numéro de segment.

        Exemples :
            hour_to_seg(23.5)        → segment correspondant à 23h30 le jour de départ
            hour_to_seg(4, jour=1)   → segment correspondant à 4h00 le lendemain
        """
        hours_from_start = jour * 24 + hour - self.start_hour
        return int(hours_from_start * self.speed_kmh * self.nb_segments / self.total_km)

    def is_compatible(self, coureur_1: str, coureur_2: str) -> bool:
        """Retourne True si coureur_1 et coureur_2 peuvent former un binôme."""
        return self.compat_matrix.get((coureur_1, coureur_2), 0) > 0

    def compat_score(self, coureur_1: str, coureur_2: str) -> int:
        """Retourne le score de compatibilité (0, 1 ou 2)."""
        return self.compat_matrix.get((coureur_1, coureur_2), 0)

    def _resolved_repos_jour(self, coureur: Coureur) -> int:
        return coureur.repos_jour if coureur.repos_jour is not None else self.repos_jour_default

    def _resolved_repos_nuit(self, coureur: Coureur) -> int:
        return coureur.repos_nuit if coureur.repos_nuit is not None else self.repos_nuit_default

    def _resolved_solo_max(self, coureur: Coureur) -> int:
        return coureur.solo_max if coureur.solo_max is not None else self.solo_max_default

    def _resolved_nuit_max(self, coureur: Coureur) -> int:
        return coureur.nuit_max if coureur.nuit_max is not None else self.nuit_max_default

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

        req_sizes = {r: [max(spec.size) for spec in cd.relais] for r, cd in self.runners_data.items()}
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
                for r2 in self.runners[i + 1:]:
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
            return 0

        bound = solver.Objective().Value()

        # Solos par coureur : relais non appariés dans la solution LP
        binomes_r: dict[str, dict[int, float]] = {r: defaultdict(float) for r in self.runners}
        for (r1, r2, s), var in b.items():
            v = var.solution_value()
            binomes_r[r1][s] += v
            binomes_r[r2][s] += v

        solo_km = {
            r: sum((counts[r].get(s, 0) - binomes_r[r][s]) * s * self.segment_km for s in all_sizes)
            for r in self.runners
        }
        solo_nb = {
            r: sum(max(0.0, counts[r].get(s, 0) - binomes_r[r][s]) for s in all_sizes)
            for r in self.runners
        }
        total_solo_nb = sum(solo_nb.values())
        total_solo_km = sum(solo_km.values())

        self.lp_upper_bound_exact = bound
        self.lp_upper_bound = int(bound)
        self.lp_solo_nb = total_solo_nb
        self.lp_solo_km = total_solo_km
        self._lp_computed = True

        return self.lp_upper_bound

    def _ensure_lp(self):
        """Déclenche le calcul LP si ce n'est pas encore fait."""
        if not self._lp_computed:
            self.compute_upper_bound()

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
        print("TYPES DE RELAIS")
        print("-" * 60)
        for name, segs in self.relay_types.items():
            km_vals = sorted(s * self.segment_km for s in segs)
            print(f"  {name:6s} : {sorted(segs)} segs  ({[round(v, 1) for v in km_vals]} km)")

        print()
        print("COUREURS")
        print("-" * 60)
        km_engages = 0
        for name, coureur in self.runners_data.items():
            req_sizes = [max(spec.size) for spec in coureur.relais]
            km = sum(req_sizes) * self.segment_km
            km_engages += km
            flags = []
            nuit_max = self._resolved_nuit_max(coureur)
            solo_max = self._resolved_solo_max(coureur)
            repos_jour = self._resolved_repos_jour(coureur)
            repos_nuit = self._resolved_repos_nuit(coureur)
            if nuit_max == 0:
                flags.append("nuit interdit")
            elif nuit_max != self.nuit_max_default:
                flags.append(f"nuit_max={nuit_max}")
            if solo_max == 0:
                flags.append("solo interdit")
            elif solo_max != self.solo_max_default:
                flags.append(f"solo_max={solo_max}")
            if repos_jour != self.repos_jour_default:
                flags.append(f"repos_jour={repos_jour} segs ({repos_jour * self.segment_duration:.1f}h)")  # fmt: skip
            if repos_nuit != self.repos_nuit_default:
                flags.append(f"repos_nuit={repos_nuit} segs ({repos_nuit * self.segment_duration:.1f}h)")  # fmt: skip
            n_pinned = sum(1 for spec in coureur.relais if spec.pinned is not None)
            if n_pinned:
                flags.append(f"fixes×{n_pinned}")
            flex_count = sum(1 for spec in coureur.relais if len(spec.size) > 1)
            if flex_count:
                flags.append(f"flex×{flex_count}")
            flag_str = f"  [{', '.join(flags)}]" if flags else ""
            sizes_str = " + ".join(
                (f"[{min(spec.size) * self.segment_km:.1f}–{max(spec.size) * self.segment_km:.1f}]" if len(spec.size) > 1 else f"{max(spec.size) * self.segment_km:.1f}")
                for spec in coureur.relais
            )
            print(f"  {name:12s} : {km:.0f} km = {sizes_str} km{flag_str}")
        print(
            f"  {'TOTAL':12s}   {km_engages:.0f} km engagés  (minimum {2 * self.total_km - km_engages:.1f} km en solo)"
        )
        self._ensure_lp()
        if self.lp_upper_bound is not None:
            print(f"\n  Majorant (relaxation LP) : {self.lp_upper_bound_exact:.4f} → {self.lp_upper_bound} binômes")
            print(f"  Solos (borne basse LP)   : {self.lp_solo_nb:.2f} relais  ({self.lp_solo_km:.0f} km)")

        print()
        print("COMPATIBILITÉS (binômes possibles)")
        print("-" * 60)
        for name in self.runners:
            partners = sorted(r for r in self.runners if r != name and self.is_compatible(name, r))
            compat_str = ", ".join(partners) if partners else "— aucune"
            print(f"  {name:12s} : {compat_str}")

        print()
        print("RELAIS EPINGLÉS")
        print("-" * 60)
        paired = self.paired_relays
        if paired:
            print("  Pairings :")
            for r1, k1, r2, k2 in paired:
                print(f"    {r1}[{k1}]+{r2}[{k2}]")
        else:
            print("  Pairings : (aucun)")
        pinned_runners = [
            (name, k, spec)
            for name, coureur in self.runners_data.items()
            for k, spec in enumerate(coureur.relais)
            if spec.pinned is not None
        ]
        if pinned_runners:
            print("  Relais individuels fixes :")
            for name, k, spec in pinned_runners:
                h = self.segment_start_hour(spec.pinned)
                req = max(spec.size)
                size_str = f"{req} segs ({req * self.segment_km:.1f} km)"
                if len(spec.size) > 1:
                    size_str += f" [flex {min(spec.size)}–{max(spec.size)} segs]"
                print(f"    {name} relais[{k}] : seg {spec.pinned} ({h:.1f}h), taille {size_str}")
        else:
            print("  Relais individuels fixes : (aucun)")

        print("=" * 60)
