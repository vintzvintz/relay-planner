from dataclasses import dataclass
import math

# Noms des types de relais (clés du dict relay_types de Constraints)
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
    r13 = math.floor(12.5 / seg_km)
    r15 = math.ceil(15 / seg_km)    # pas moins de 15km
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
    paired_with : (runner_name, relay_index) du relais partenaire, positionné via SharedLeg.
    window      : le relais doit être entièrement inclus dans [start, end] (segments, inclus).
    pinned      : segment de départ fixé. Incompatible avec flex (len(size) > 1).
    """
    size: set[int]
    paired_with: tuple[str, int] | None = None  # (runner_name, relay_index)
    window: list[tuple[int, int]] | None = None  # liste d'intervalles [start, end] inclus
    pinned: int | None = None


class RelayHandle:
    """Référence interne à un relais spécifique d'un coureur.

    Utilisé par SharedLeg pour enregistrer les pairings via _pair_with().
    """

    def __init__(self, runner_name: str, relay_index: int, spec: "RelaySpec"):
        self.runner_name = runner_name
        self.relay_index = relay_index
        self._spec = spec

    def _pair_with(self, other: "RelayHandle") -> None:
        self._spec.paired_with = (other.runner_name, other.relay_index)
        other._spec.paired_with = (self.runner_name, self.relay_index)


class SharedLeg:
    """Relais partagé entre plusieurs coureurs, créé via Constraints.new_relay().

    Passer la même instance à add_relay() de plusieurs coureurs les apparie automatiquement.
    Limité à 2 coureurs (un binôme).
    """

    def __init__(self, size: set[int]):
        self.size = size
        self._handles: list[RelayHandle] = []

    def _register(self, handle: RelayHandle) -> None:
        if len(self._handles) >= 2:
            raise ValueError("Un SharedLeg ne peut être partagé qu'entre 2 coureurs.")
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
    repos_jour: int | None = None         # None = utilise repos_jour_default du Constraints
    repos_nuit: int | None = None         # None = utilise repos_nuit_default du Constraints
    solo_max: int | None = None           # None = utilise solo_max_default du Constraints
    nuit_max: int | None = None           # None = utilise nuit_max_default du Constraints
    max_same_partenaire: int | None = None  # None = utilise max_same_partenaire_default


@dataclass
class Intervals:
    """Abstraction d'une ou plusieurs plages de segments.

    Utilisée pour définir les contraintes de placement (window) et les dispos coureurs.
    Chaque tuple (start, end) est un intervalle de segments [start, end] inclus.
    """
    intervals: list[tuple[int, int]]




class RunnerBuilder:
    """Builder fluide pour déclarer les relais d'un coureur.

    Créé via Constraints.new_runner(). Les appels à add_relay() accumulent
    des RelaySpec dans le Coureur interne, qui est enregistré dans runners_data.
    """

    def __init__(self, name: str, coureur: Coureur, constraints: "Constraints"):
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
        size: "str | SharedLeg",
        *,
        nb: int = 1,
        window: "Intervals | tuple[int, int] | None" = None,
        pinned: int | None = None,
    ) -> "RunnerBuilder":
        """Ajoute nb relais identiques au coureur et retourne self pour le chaînage.

        size : nom de type (str) ou SharedLeg (créé via constraints.new_relay()).
               Pour un SharedLeg, nb est ignoré.
        """
        if not isinstance(size, (str, SharedLeg)):
            raise TypeError(f"size doit être un nom de type (str) ou un SharedLeg, pas {type(size).__name__}.")

        c = self._constraints

        window_list: list[tuple[int, int]] | None = None
        if isinstance(window, Intervals):
            window_list = window.intervals
        elif isinstance(window, tuple):
            window_list = [window]

        # Convertir les bornes de window (indices actifs) en indices temps
        if window_list is not None:
            window_list = [
                (c.active_to_time_seg(s), c.active_to_time_seg(e))
                for s, e in window_list
            ]

        # Convertir pinned (index actif) en index temps
        time_pinned: int | None = None
        if pinned is not None:
            time_pinned = c.active_to_time_seg(pinned)

        if isinstance(size, str):
            size = c.relay_types[size]

        if isinstance(size, SharedLeg):
            if nb != 1:
                raise ValueError("nb>1 n'est pas compatible avec un SharedLeg.")
            idx = len(self._coureur.relais)
            spec = RelaySpec(size=size.size, window=window_list, pinned=time_pinned)
            self._coureur.relais.append(spec)
            size._register(RelayHandle(self.name, idx, spec))
            return self

        for _ in range(nb):
            self._coureur.relais.append(RelaySpec(size=size, window=window_list, pinned=time_pinned))
        return self



class Constraints:
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
        solo_autorise_debut: float | None = None,
        solo_autorise_fin: float | None = None,
        max_same_partenaire: int | None = None,
        enable_flex: bool = True,
        allow_flex_flex: bool = True,
        profil_csv: str | None = None,
    ):
        self.total_km = total_km
        # nb_segments (paramètre) = nombre de segments ACTIFS (course).
        # nb_active_segments est fixe ; nb_segments grandit à chaque add_pause().
        self.nb_active_segments: int = nb_segments
        self.nb_segments: int = nb_segments  # espace-temps ; augmente avec les pauses
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
        self.solo_autorise_debut: float = solo_autorise_debut
        self.solo_autorise_fin: float = solo_autorise_fin
        self.repos_jour_default: int = self.duration_to_segs(repos_jour_heures)
        self.repos_nuit_default: int = self.duration_to_segs(repos_nuit_heures)

        # Pauses : plages de segments inactifs dans l'espace-temps.
        # inactive_ranges[i] = (time_start, time_end) — segment inactifs [start, end)
        # _pause_active_segs[i] = index du segment actif où la pause s'insère (arg. de add_pause)
        self.inactive_ranges: list[tuple[int, int]] = []
        self.inactive_segments: set[int] = set()
        self.active_segments: list[int] = list(range(nb_segments))
        self._pause_active_segs: list[int] = []

        self.runners_data: dict[str, Coureur] = {}
        self.once_max: list[tuple[str, str, int]] = []
        self.max_same_partenaire: int | None = max_same_partenaire
        self.relay_types: dict[str, set[int]] = make_relay_types(nb_segments, total_km, enable_flex)
        self.allow_flex_flex: bool = allow_flex_flex
        self.profil_csv = profil_csv
        self._profil = None  # lazy-init

        # Index des coureurs connus (pour validation dans new_runner)
        self._known_runners: set[str] = {name for pair in self.compat_matrix for name in pair}

        # Résultat de la relaxation LP (rempli à la première demande via lp_bounds)
        self._lp_computed: bool = False
        self._lp_bounds = None

    # ------------------------------------------------------------------
    # API déclarative
    # ------------------------------------------------------------------

    def add_pause(self, seg: int, duree: float) -> None:
        """Déclare une pause après le segment actif seg, de durée duree heures.

        seg  : index de segment ACTIF (0..nb_active_segments-1).
               Utiliser c.km_to_seg() ou c.hour_to_seg() pour convertir depuis km ou heures.
        duree: durée de la pause en heures (> 0).

        Doit être appelé avant new_runner() et add_relay(), dans l'ordre croissant de seg.
        """
        if self.runners_data:
            raise RuntimeError(
                "add_pause() doit être appelé avant new_runner() — "
                "des coureurs ont déjà été déclarés."
            )
        assert duree > 0, f"Durée de pause nulle ou négative : {duree}"
        assert 0 < seg < self.nb_active_segments, f"Segment de pause hors bornes : {seg}"

        pause_seg_dur = self.duration_to_segs(duree)
        # Conversion index actif → index temps : décaler par les segments inactifs déjà insérés.
        total_inactive_so_far = self.nb_segments - self.nb_active_segments
        time_start = seg + total_inactive_so_far
        time_end = time_start + pause_seg_dur

        self._pause_active_segs.append(seg)
        self.inactive_ranges.append((time_start, time_end))
        for s in range(time_start, time_end):
            self.inactive_segments.add(s)
        self.nb_segments += pause_seg_dur
        # Reconstruire active_segments dans l'ordre
        self.active_segments = [s for s in range(self.nb_segments) if s not in self.inactive_segments]

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
    ) -> SharedLeg:
        """Crée un relais partagé à passer à add_relay() de deux coureurs pour les apparier."""
        if not isinstance(size, str):
            raise TypeError(f"size doit être un nom de type (str), pas {type(size).__name__}.")
        return SharedLeg(size=self.relay_types[size])

    def night_windows(self) -> Intervals:
        """Retourne un Intervals couvrant toutes les plages nocturnes, en indices ACTIFS."""
        intervals: list[tuple[int, int]] = []
        in_night = False
        seg_start = 0
        for s in self.active_segments:
            active_idx = self.time_seg_to_active(s)
            if self.is_night(s):
                if not in_night:
                    seg_start = active_idx
                    in_night = True
            else:
                if in_night:
                    intervals.append((seg_start, active_idx - 1))
                    in_night = False
        if in_night:
            intervals.append((seg_start, self.nb_active_segments - 1))
        return Intervals(intervals)

    # ------------------------------------------------------------------
    # Propriétés et méthodes utilitaires
    # ------------------------------------------------------------------

    @property
    def last_active_seg(self) -> int:
        """Borne supérieure exclusive des segments actifs (= nb_active_segments).

        À utiliser dans Intervals pour exprimer "jusqu'à la fin de la course",
        en remplacement de c.nb_segments qui est un index espace-temps.
        """
        return self.nb_active_segments

    @property
    def paired_relays(self) -> list[tuple[str, int, str, int]]:
        """Tuples (r1, k1, r2, k2) pour tous les pairings déclarés via SharedLeg."""
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
    def profil(self):
        if self._profil is None and self.profil_csv is not None:
            from .profil import load_profile
            self._profil = load_profile(self.profil_csv)
        return self._profil

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
    def has_flex(self) -> bool:
        """True si au moins un relais a une taille variable (domaine de taille > 1)."""
        return any(
            len(spec.size) > 1
            for coureur in self.runners_data.values()
            for spec in coureur.relais
        )

    @property
    def night_segments(self):
        return set(s for s in range(self.nb_segments) if self.is_night(s))

    @property
    def segment_km(self) -> float:
        """longueur d'un segment ACTIF en km"""
        return self.total_km / self.nb_active_segments

    @property
    def segment_duration(self) -> float:
        """durée d'un quantum de temps (segment) en heures"""
        return self.segment_km / self.speed_kmh

    def segment_start_hour(self, seg: int) -> float:
        """Heure de début du quantum de temps seg (index dans l'espace-temps), en heures depuis minuit mercredi.

        Dans le nouveau modèle, chaque segment (actif ou inactif) représente un quantum
        de temps fixe : segment_start_hour est simplement linéaire.
        """
        return self.start_hour + seg * self.segment_duration

    def active_to_time_seg(self, active_idx: int) -> int:
        """Convertit un index de segment actif en index de segment temps.

        Le décalage est la somme des durées (en segs) de toutes les pauses
        qui s'insèrent avant ou à active_idx.
        """
        shift = 0
        for i, ps in enumerate(self._pause_active_segs):
            if ps <= active_idx:
                a, b = self.inactive_ranges[i]
                shift += b - a
        return active_idx + shift

    def time_seg_to_active(self, seg: int) -> int:
        """Convertit un index de segment temps en index de segment actif.

        Compte le nombre de segments inactifs strictement avant seg.
        """
        return seg - sum(1 for s in self.inactive_segments if s < seg)

    def is_active(self, seg: int) -> bool:
        """Retourne True si le segment temps seg est un segment actif (course en cours)."""
        return seg not in self.inactive_segments

    def is_night(self, seg: int) -> bool:
        """Vrai si le segment démarre entre nuit_debut et nuit_fin (n'importe quel jour)."""
        h = self.segment_start_hour(seg) % 24
        if self.nuit_debut <= self.nuit_fin:
            return self.nuit_debut <= h < self.nuit_fin
        else:
            return h >= self.nuit_debut or h < self.nuit_fin

    def is_solo_forbidden(self, seg: int) -> bool:
        """Vrai si le segment est hors de la plage solo_autorise_debut/solo_autorise_fin (solos interdits)."""
        if self.solo_autorise_debut is None:
            return False
        h = self.segment_start_hour(seg) % 24
        if self.solo_autorise_debut <= self.solo_autorise_fin:
            return not (self.solo_autorise_debut <= h < self.solo_autorise_fin)
        else:
            return not (h >= self.solo_autorise_debut or h < self.solo_autorise_fin)

    @property
    def solo_forbidden_segments(self) -> set[int]:
        return set(s for s in range(self.nb_segments) if self.is_solo_forbidden(s))

    def duration_to_segs(self, hours: float) -> int:
        """Convertit une durée en heures en nombre de segments temps (arrondi au supérieur)."""
        return math.ceil(hours / self.segment_duration)

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
        """Convertit une distance en km en index de segment ACTIF."""
        return math.floor(km * self.nb_active_segments / self.total_km)

    def hour_to_seg(self, hour: float, jour: int = 0) -> int:
        """Convertit une heure absolue (+ décalage en jours) en index de segment ACTIF.

        Exemples :
            hour_to_seg(23.5)        → segment actif correspondant à 23h30 le jour de départ
            hour_to_seg(4, jour=1)   → segment actif correspondant à 4h00 le lendemain
        """
        h_abs = jour * 24 + hour
        time_seg = int((h_abs - self.start_hour) / self.segment_duration)
        return self.time_seg_to_active(time_seg)

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

    @property
    def lp_bounds(self):
        if not self._lp_computed:
            from relay.upper_bound import compute_upper_bound
            compute_upper_bound(self)
        return self._lp_bounds

    def print_summary(self) -> None:
        """Affiche un résumé complet des données d'entrée du problème."""

        print("=" * 60)
        print("RÉSUMÉ DES DONNÉES D'ENTRÉE")
        print("=" * 60)
        nb_total_str = f" ({self.nb_segments} en tout avec pauses)" if self.inactive_ranges else ""
        print(
            f"  Parcours    : {self.total_km:.1f} km, {self.nb_active_segments} segments actifs de {self.segment_km:.1f} km{nb_total_str}"
        )
        print(
            f"  Vitesse     : {self.speed_kmh} km/h → {self.segment_duration * 60:.1f} min/segment"
        )
        print(f"  Départ      : mercredi {self.start_hour}h00")
        print(f"  Repos jour  : {self.repos_jour_default} segments = {self.repos_jour_default * self.segment_duration:.1f}h")  # fmt: skip
        print(f"  Repos nuit  : {self.repos_nuit_default} segments = {self.repos_nuit_default * self.segment_duration:.1f}h")  # fmt: skip
        print(f"  Nuit (repos): {self.nuit_debut}h–{self.nuit_fin}h")
        print(f"  Solo autorisé: {self.solo_autorise_debut}h–{self.solo_autorise_fin}h")

        if self.inactive_ranges:
            print()
            print("PAUSES PLANIFIÉES")
            print("-" * 60)
            for i, (a, b) in enumerate(self.inactive_ranges):
                h_start = self.segment_start_hour(a)
                h_end = self.segment_start_hour(b)
                dur_h = h_end - h_start
                jour = int(h_start // 24)
                h_local = h_start % 24
                ps = self._pause_active_segs[i]
                print(
                    f"  Pause {i+1} : j{jour} {h_local:.2f}h, durée {dur_h:.2f}h,"
                    f" frontière seg actif {ps}, segs temps [{a}, {b})"
                )

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
        if (lp := self.lp_bounds) is not None:
            print(f"\n  Majorant score : {lp.upper_bound}")
            print(f"  Minorant solos : {lp.solo_nb:.2f} relais  ({lp.solo_km:.0f} km)")

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
