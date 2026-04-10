"""
relay/constraints.py

Contraintes pour le modèle à points de passage (waypoints).

Les relais couvrent un nombre entier d'arcs entre points consécutifs de
longueurs variables. Contrairement au modèle uniforme, la taille d'un relais
est un résultat (distance courue) et non un input fixe.

Unités internes CP-SAT :
  - distances en mètres entiers (arrondi de waypoints_km * 1000)
  - temps en minutes entières
"""

from __future__ import annotations

import json
from collections import namedtuple
from copy import copy
from dataclasses import dataclass, field
from .parcours import Parcours, load_gpx


# Namedtuple utilitaire pour pré-définir des gabarits de relais.
# Usage : LONG = RelayPreset(km=20, min=17, max=23)
#         runner.add_relay(LONG)           # seul argument positionnel
Preset = namedtuple("RelayPreset", ["km", "min", "max"], defaults=[None, None])

Pin = namedtuple("Pin", ["start", "end"], defaults=[None, None])



Interval = namedtuple("Interval", ["lo", "hi"])


def _to_window(window: "Interval | list[Interval] | None") -> "list[tuple[int,int]] | None":
    """Convertit Interval / list[Interval] → format interne list[tuple[int,int]]."""
    if window is None:
        return None
    if isinstance(window, Interval):
        return [(window.lo, window.hi)]
    return [(iv.lo, iv.hi) for iv in window]


@dataclass
class RelaySpec:
    """Descripteur d'un relais dans le modèle waypoint.

    target_m    : distance cible en mètres (input, pas la taille réelle).
    min_m       : distance minimale en mètres (None = pas de borne inférieure).
    max_m       : distance maximale en mètres (None = pas de borne supérieure).
    paired_with : (runner_name, relay_index) si binôme forcé via SharedLeg.
    window      : liste de (point_lo, point_hi) — le relais doit tenir dans l'un des intervalles.
    pinned      : (start_point, end_point) — départ et arrivée fixés (None = libre).
    dplus_max   : D+ + D- maximum en mètres (None = pas de borne). Requiert un profil altimétrique en cache.
    """
    target_m: int
    min_m: int | None = None
    max_m: int | None = None
    paired_with: tuple[str, int] | None = None
    window: list[tuple[int, int]] | None = None
    pinned_start: int | None = None
    pinned_end: int | None = None
    dplus_max: int | None = None
    solo: bool | None = None
    chained_to_next: bool = False

    def size_m(self, use_max: bool = False) -> int:
        """Taille de référence du relais : max_m si use_max et défini, sinon target_m."""
        if use_max and self.max_m is not None:
            return self.max_m
        return self.target_m

    def to_dict(self) -> dict:
        return {
            "target_m": self.target_m,
            "min_m": self.min_m,
            "max_m": self.max_m,
            "paired_with": list(self.paired_with) if self.paired_with else None,
            "window": self.window,
            "pinned_start": self.pinned_start,
            "pinned_end": self.pinned_end,
            "dplus_max": self.dplus_max,
            "solo": self.solo,
            "chained_to_next": self.chained_to_next,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RelaySpec":
        return cls(
            target_m=d["target_m"],
            min_m=d["min_m"],
            max_m=d["max_m"],
            paired_with=tuple(d["paired_with"]) if d["paired_with"] else None,
            window=[tuple(iv) for iv in d["window"]] if d["window"] else None,
            pinned_start=d.get("pinned_start"),
            pinned_end=d.get("pinned_end"),
            dplus_max=d.get("dplus_max"),
            solo=d.get("solo"),
            chained_to_next=d.get("chained_to_next", False),
        )


class SharedLeg:
    """Relais partagé entre deux coureurs (binôme forcé)."""

    def __init__(self, target_m: int, min_m: int | None = None, max_m: int | None = None):
        self.target_m = target_m
        self.min_m = min_m
        self.max_m = max_m
        self._entries: list[tuple[str, int, RelaySpec]] = []

    def _register(self, runner_name: str, relay_index: int, spec: RelaySpec) -> None:
        if len(self._entries) >= 2:
            raise ValueError("Un relais ne peut être partagé qu'entre 2 coureurs.")
        for other_name, other_idx, other_spec in self._entries:
            spec.paired_with = (other_name, other_idx)
            other_spec.paired_with = (runner_name, relay_index)
        self._entries.append((runner_name, relay_index, spec))


@dataclass
class RunnerOptions:
    solo_max: int | None = None
    nuit_max: int | None = None
    repos_jour_min: int | None = None   # en minutes
    repos_nuit_min: int | None = None   # en minutes
    max_same_partenaire: int | None = None
    lvl: int | None = None

    def to_dict(self) -> dict:
        return {
            "solo_max": self.solo_max,
            "nuit_max": self.nuit_max,
            "repos_jour_min": self.repos_jour_min,
            "repos_nuit_min": self.repos_nuit_min,
            "max_same_partenaire": self.max_same_partenaire,
            "lvl": self.lvl,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RunnerOptions":
        return cls(
            solo_max=d["solo_max"],
            nuit_max=d["nuit_max"],
            repos_jour_min=d["repos_jour_min"],
            repos_nuit_min=d["repos_nuit_min"],
            max_same_partenaire=d["max_same_partenaire"],
            lvl=d.get("lvl"),
        )


@dataclass
class Coureur:
    relais: list[RelaySpec] = field(default_factory=list)
    options: RunnerOptions = field(default_factory=RunnerOptions)


class RunnerBuilder:
    """Builder fluide pour déclarer les relais d'un coureur (modèle waypoint)."""

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
        opts = self._coureur.options
        if solo_max is not None:
            opts.solo_max = solo_max
        if nuit_max is not None:
            opts.nuit_max = nuit_max
        if repos_jour is not None:
            opts.repos_jour_min = round(repos_jour * 60)
        if repos_nuit is not None:
            opts.repos_nuit_min = round(repos_nuit * 60)
        if max_same_partenaire is not None:
            opts.max_same_partenaire = max_same_partenaire
        return self

    def add_relay(
        self,
        *presets: "Preset | SharedLeg",
        window: "Interval | list[Interval] | None" = None,
        pinned: "Pin | None" = None,
        dplus_max: int | None = None,
        solo: bool | None = None,
    ) -> "RunnerBuilder":
        """Ajoute un ou plusieurs relais.

        Un seul preset : relais simple (pas de chaînage).
        Plusieurs presets : relais enchaînés (end[k] == start[k+1], sans repos entre eux).

        presets  : un ou plusieurs Preset ou SharedLeg (arguments positionnels).
        window   : Interval(s) — produit par c.interval_km() / c.interval_time() / c.interval_waypoints().
        pinned   : Pin produit par c.new_pin() — épingle le départ et/ou l'arrivée.
        dplus_max: D+ + D- maximum par relais individuel.
        solo     : True/False/None — appliqué aux Preset (ignoré pour les SharedLeg).
        """
        if not presets:
            raise ValueError("add_relay() nécessite au moins un preset.")
        for p in presets:
            if not isinstance(p, (Preset, SharedLeg)):
                raise TypeError(
                    f"add_relay() n'accepte que des Preset ou SharedLeg, pas {type(p).__name__!r}."
                )

        chained = len(presets) > 1
        pinned_start = pinned.start if pinned is not None else None
        pinned_end   = pinned.end   if pinned is not None else None
        win = _to_window(window)

        for i, preset in enumerate(presets):
            is_first = (i == 0)
            is_last  = (i == len(presets) - 1)
            ps = pinned_start if (not chained or is_first) else None
            pe = pinned_end   if (not chained or is_last)  else None

            if isinstance(preset, SharedLeg):
                if solo is True:
                    raise ValueError("solo=True est incompatible avec SharedLeg.")
                target_m, min_m, max_m = preset.target_m, preset.min_m, preset.max_m
                solo_eff = None
            else:
                target_m = round(preset.km * 1000)
                min_m    = round(preset.min * 1000) if preset.min is not None else None
                max_m    = round(preset.max * 1000) if preset.max is not None else None
                solo_eff = solo

            spec = RelaySpec(
                target_m=target_m,
                min_m=min_m,
                max_m=max_m,
                window=win,
                pinned_start=ps,
                pinned_end=pe,
                dplus_max=dplus_max,
                solo=solo_eff,
                chained_to_next=(chained and not is_last),
            )
            relay_idx = len(self._coureur.relais)
            self._coureur.relais.append(spec)
            if isinstance(preset, SharedLeg):
                preset._register(self.name, relay_idx, spec)
        return self


class Constraints:
    """
    Contraintes pour le modèle à points de passage.

    parcours : chemin vers le fichier GPX, ou instance de Parcours.
    """

    def __init__(
        self,

        # paramètres globaux
        parcours: str | Parcours,
        speed_kmh: float,
        start_hour: float,
        compat_matrix: "str | dict[tuple[str, str], int]",
        solo_max_km: float,

        # options par défaut des coureurs
        solo_max_default: int,
        nuit_max_default: int,
        repos_jour_heures: float,
        repos_nuit_heures: float,
        max_same_partenaire: int | None,
    ):
        if isinstance(parcours, str):
            parcours = load_gpx(parcours)
        self.parcours = parcours

        pts: list[dict] = list(parcours.waypoints)
        if pts[0]["km"] != 0.0:
            raise ValueError(
                f"Le premier waypoint doit être au km 0.0 (départ). "
                f"Valeur reçue : km={pts[0]['km']}."
            )
        self.waypoints: list[dict] = pts
        waypoints_km: list[float] = [pt["km"] for pt in pts]

        assert len(waypoints_km) >= 2, "Il faut au moins 2 points."
        assert waypoints_km == sorted(waypoints_km), "Les points doivent être en ordre croissant de km."

        self.waypoints_km = list(waypoints_km)
        self.speed_kmh = speed_kmh
        self.start_hour = start_hour
        self.total_km = waypoints_km[-1]
        self.nb_points = len(waypoints_km)
        self.nb_arcs = self.nb_points - 1

        # Distances cumulatives en mètres (entiers)
        self.cumul_m: list[int] = [round(km * 1000) for km in waypoints_km]

        # Longueur de chaque arc en km
        self.arc_km: list[float] = [
            waypoints_km[i + 1] - waypoints_km[i] for i in range(self.nb_arcs)
        ]

        # Temps cumulatif en minutes (base, avant pauses)
        # cumul_temps[i] = minutes depuis le départ pour atteindre le point i
        self.cumul_temps: list[int] = [
            round(waypoints_km[i] / speed_kmh * 60) for i in range(self.nb_points)
        ]

        # Matrice de compatibilité : chemin xlsx ou dict pré-construit
        if isinstance(compat_matrix, str):
            from .compat import read_compat_matrix
            raw = read_compat_matrix(compat_matrix)
        else:
            raw = compat_matrix
        # Triangle inférieur → symétrique
        self.compat_matrix: dict[tuple[str, str], int] = {
            **raw,
            **{(b, a): v for (a, b), v in raw.items()},
        }
        self._known_runners: set[str] = {name for pair in self.compat_matrix for name in pair}

        # Distances solo max en mètres
        self.solo_max_m: int = round(solo_max_km * 1000)

        # Options par défaut
        self.defaults = RunnerOptions(
            solo_max=solo_max_default,
            nuit_max=nuit_max_default,
            repos_jour_min=round(repos_jour_heures * 60),
            repos_nuit_min=round(repos_nuit_heures * 60),
            max_same_partenaire=max_same_partenaire,
        )

        # Intervalles nuit et solo-interdit (initialement vides, remplis par add_night/add_no_solo)
        self._intervals_night: list[tuple[int, int]] = []    # liste de (wp_debut, wp_fin)
        self._intervals_no_solo: list[tuple[int, int]] = []  # liste de (wp_debut, wp_fin)

        self.runners_data: dict[str, Coureur] = {}
        self._shared_legs: list[SharedLeg] = []
        self.max_duos: list[tuple[str, str, int]] = []
        self._upper_bounds: tuple | None = None  # (ub_target, ub_max) | None
        self._upper_bounds_computed: bool = False
        self._pauses: list[tuple[int, float]] = []  # (after_point utilisateur, duree_heures)
        self._base_waypoints: list[dict] = list(self.waypoints)  # waypoints sans pauses
        self.pause_arcs: set[int] = set()  # indices d'arcs correspondant à des pauses

        # Flag : passe à True dès qu'une conversion km/heure → index est appelée.
        # add_pause() lève une exception si True (les arcs ne doivent plus changer).
        self._arcs_frozen: bool = False


    # ------------------------------------------------------------------
    # add_pause : décale cumul_temps après le point donné
    # ------------------------------------------------------------------

    def add_pause(
        self,
        duree_heures: float,
        *,
        wp: int | None = None,
        km: float | None = None,
        heure: float | None = None,
        jour: int | None = None,
    ) -> "Constraints":
        """Déclare une pause après un waypoint.

        La position de la pause est spécifiée par exactement l'un des paramètres :
          wp=    : indice de waypoint (espace utilisateur, sans pauses)
          km=    : km cumulé — waypoint le plus proche
          heure= : heure de passage — doit être accompagné de jour= (et réciproquement)

        Insère un point intermédiaire (arc de 0 km) entre le point choisi et le
        suivant. L'arc correspondant est enregistré dans pause_arcs et exclu de
        la contrainte de couverture.

        Doit être appelé avant toute factory d'Interval (interval_km, interval_time, interval_waypoints).
        Retourne self (chaînable).
        """
        n = sum(x is not None for x in (wp, km, heure))
        if n == 0:
            raise ValueError("add_pause() requiert exactement l'un de : wp=, km=, heure=.")
        if n > 1:
            raise ValueError("add_pause() : wp=, km= et heure= sont mutuellement exclusifs.")
        if (heure is None) != (jour is None):
            raise ValueError("add_pause() : heure= et jour= doivent être spécifiés ensemble.")

        if self._arcs_frozen:
            raise RuntimeError(
                "add_pause() ne peut pas être appelé après une factory d'Interval : "
                "les index déjà calculés seraient incohérents."
            )

        if wp is not None:
            after_point = wp
        elif km is not None:
            after_point = self._km_to_point(km)
        else:
            after_point = self._hour_to_point(heure, jour if jour is not None else 0)

        n_base = len(self._base_waypoints)
        if not (0 <= after_point < n_base - 1):
            raise ValueError(f"add_pause() : position hors bornes (after_point={after_point}, n_base={n_base}).")

        self._pauses.append((after_point, duree_heures))
        self._rebuild_from_pauses()
        return self

    def add_night(self, interval: Interval) -> "Constraints":
        """Déclare les plages horaires nocturnes.

        Chaque Interval doit être construit avec interval_time() ou interval_km().
        Remplace toute déclaration précédente. Retourne self (chaînable).

        Exemple :
            c.add_night([c.interval_time(23, 0, 6, 1)])
        """
        self._intervals_night.append((interval.lo, interval.hi))
        return self

    def add_no_solo(self, interval: Interval) -> "Constraints":
        """Déclare les plages de points où les relais solo sont interdits.

        Chaque Interval doit être construit avec interval_time() ou interval_km().
        Remplace toute déclaration précédente. Retourne self (chaînable).

        Exemple :
            c.add_no_solo([c.interval_time(23, 0, 6, 1)])
        """
        self._intervals_no_solo.append((interval.lo, interval.hi))
        return self

    def _rebuild_from_pauses(self) -> None:
        """Reconstruit waypoints, cumul_m, arc_km, cumul_temps et pause_arcs
        depuis _base_waypoints et _pauses (triées par after_point utilisateur)."""
        base = self._base_waypoints
        base_km = [pt["km"] for pt in base]
        speed = self.speed_kmh

        waypoints: list[dict] = []
        waypoints_km: list[float] = []
        cumul_m: list[int] = []
        cumul_temps: list[int] = []
        pause_arcs: set[int] = set()

        # Index des pauses dans l'espace utilisateur, triées
        pauses_by_user = sorted(self._pauses, key=lambda p: p[0])

        # Map user_index → durée de pause après ce point (0 si pas de pause)
        pause_after: dict[int, float] = {}
        for user_pt, dur_h in pauses_by_user:
            pause_after[user_pt] = pause_after.get(user_pt, 0.0) + dur_h

        elapsed_min = 0
        for i, pt in enumerate(base):
            waypoints.append(pt)
            km = base_km[i]
            waypoints_km.append(km)
            cumul_m.append(round(km * 1000))
            cumul_temps.append(round(km / speed * 60) + elapsed_min)

            if i in pause_after:
                dur_h = pause_after[i]
                internal_arc = len(waypoints) - 1  # arc from current point to fictif
                pause_arcs.add(internal_arc)
                # Insérer le point fictif
                waypoints.append({k: v for k, v in pt.items()})
                waypoints_km.append(km)
                cumul_m.append(round(km * 1000))
                elapsed_min += round(dur_h * 60)
                cumul_temps.append(round(km / speed * 60) + elapsed_min)

        self.waypoints = waypoints
        self.waypoints_km = waypoints_km
        self.cumul_m = cumul_m
        self.cumul_temps = cumul_temps
        self.pause_arcs = pause_arcs
        self.arc_km = [waypoints_km[i + 1] - waypoints_km[i] for i in range(len(waypoints) - 1)]
        self.nb_points = len(waypoints)
        self.nb_arcs = self.nb_points - 1
        self.total_km = waypoints_km[-1]

    # ------------------------------------------------------------------
    # API déclarative
    # ------------------------------------------------------------------

    def new_runner(self, name: str, lvl: int) -> RunnerBuilder:
        if name not in self._known_runners:
            raise ValueError(f"Coureur '{name}' absent de la matrice de compatibilité.")
        if not (0 <= lvl <= 5):
            raise ValueError(f"lvl={lvl} hors bornes [0-5]")
        coureur = Coureur(options=copy(self.defaults))
        coureur.options.lvl = lvl
        self.runners_data[name] = coureur
        return RunnerBuilder(name, coureur, self)

    def new_shared_relay(
        self,
        preset: "Preset | None" = None,
        *,
        target_km: float | None = None,
        min_km: float | None = None,
        max_km: float | None = None,
    ) -> SharedLeg:
        """Crée un relais partagé (binôme forcé).

        preset   : RelayPreset. Seul argument positionnel.
        target_km: distance cible en km (keyword-only).
        min_km   : distance minimale en km (keyword-only).
        max_km   : distance maximale en km (keyword-only).
        """
        if isinstance(preset, Preset):
            if target_km is None:
                target_km = preset.km
            if min_km is None:
                min_km = preset.min
            if max_km is None:
                max_km = preset.max
        elif preset is not None:
            raise TypeError(
                f"new_shared_relay() attend un RelayPreset, pas {type(preset).__name__!r}. "
                "Pour une distance simple, utiliser target_km= (keyword)."
            )
        if target_km is None:
            raise ValueError("new_shared_relay() requiert target_km= ou un RelayPreset.")
        leg = SharedLeg(
            target_m=round(target_km * 1000),
            min_m=round(min_km * 1000) if min_km is not None else None,
            max_m=round(max_km * 1000) if max_km is not None else None,
        )
        self._shared_legs.append(leg)
        return leg

    def add_max_duos(
        self, runner1: RunnerBuilder, runner2: RunnerBuilder, nb: int
    ) -> None:
        self.max_duos.append((runner1.name, runner2.name, nb))

    # ------------------------------------------------------------------
    # Propriétés utilitaires
    # ------------------------------------------------------------------

    @property
    def last_point(self) -> int:
        """Indice du dernier point — borne supérieure pour interval_waypoints()."""
        return self.nb_points - 1

    @property
    def cumul_dplus(self) -> tuple[list[int], list[int]] | None:
        """Tables cumulatives (cumul_dp, cumul_dm) indexées sur self.waypoints_km (avec pauses)."""
        if not self.parcours.has_profile:
            return None
        wkm = self.waypoints_km
        cumul_dp: list[int] = [0]
        cumul_dm: list[int] = [0]
        for i in range(1, len(wkm)):
            dp, dm = self.parcours.denivele(wkm[i - 1], wkm[i])
            cumul_dp.append(cumul_dp[-1] + round(dp))
            cumul_dm.append(cumul_dm[-1] + round(dm))
        return (cumul_dp, cumul_dm)

    def _ensure_upper_bounds(self):
        if not self._upper_bounds_computed:
            from .upper_bound import compute_upper_bounds
            self._upper_bounds = compute_upper_bounds(self)
            self._upper_bounds_computed = True

    @property
    def upper_bound(self):
        """Majorant heuristique du score (taille=target_m). Non garanti mais serré."""
        self._ensure_upper_bounds()
        return self._upper_bounds[0]

    @property
    def upper_bound_max(self):
        """Majorant garanti du score (taille=max_m). Toujours ≥ optimum réel."""
        self._ensure_upper_bounds()
        return self._upper_bounds[1]

    def validate(self) -> None:
        """Vérifie la cohérence des contraintes avant la construction du modèle.

        Checks:
        - Tous les SharedLeg ont exactement 2 coureurs
        - Chaque coureur a ≥1 relais
        - Tous les coureurs déclarés existent dans la compat_matrix
        - Preset.min ≤ Preset.max pour tous les relais
        - Fenêtres (window) ont lo ≤ hi
        - solo_max_m ≤ total_km
        - Aucun interval_waypoints hors bornes

        Lève ValueError avec messages clairs.
        """
        # 1. Vérifier SharedLeg
        for leg in self._shared_legs:
            if len(leg._entries) != 2:
                names = [name for name, _, _ in leg._entries]
                raise ValueError(
                    f"Un SharedLeg créé via new_shared_relay() doit être affecté à exactement "
                    f"2 coureurs via add_relay(). Il n'a été affecté qu'à : {names}."
                )

        # 2. Vérifier que tous les coureurs ont ≥1 relais
        for name in self.runners_data:
            if not self.runners_data[name].relais:
                raise ValueError(
                    f"❌ Coureur '{name}' n'a pas de relais. Options:\n"
                    f"   - Ajouter : {name}.add_relay(Preset(...))\n"
                    f"   - Ou retirer : enlever '{name}' de new_runner()"
                )

        # 3. Vérifier tous les coureurs existent dans compat_matrix
        for name in self.runners_data:
            if name not in self._known_runners:
                raise ValueError(
                    f"❌ Coureur '{name}' absent de la matrice de compatibilité.\n"
                    f"   Vérifier : compat_coureurs.xlsx ou compat_matrix dict"
                )

        # 4. Vérifier Preset.min ≤ Preset.max
        for name, coureur in self.runners_data.items():
            for k, spec in enumerate(coureur.relais):
                if spec.min_m is not None and spec.max_m is not None:
                    if spec.min_m > spec.max_m:
                        raise ValueError(
                            f"❌ Relais {k} de '{name}' : min_m > max_m "
                            f"({spec.min_m} > {spec.max_m} mètres).\n"
                            f"   Vérifier : Preset(km={spec.target_m/1000:.1f}, "
                            f"min={spec.min_m/1000:.1f}, max={spec.max_m/1000:.1f})"
                        )

        # 5. Vérifier window intervals
        for name, coureur in self.runners_data.items():
            for k, spec in enumerate(coureur.relais):
                if spec.window is not None:
                    for lo, hi in spec.window:
                        if lo > hi:
                            raise ValueError(
                                f"❌ Relais {k} de '{name}' : window invalide (lo={lo} > hi={hi}).\n"
                                f"   Vérifier : interval_km() ou interval_time() ou interval_waypoints()"
                            )
                        if not (0 <= lo <= self.nb_points - 1) or not (0 <= hi <= self.nb_points - 1):
                            raise ValueError(
                                f"❌ Relais {k} de '{name}' : window hors bornes "
                                f"({lo}, {hi}) pour {self.nb_points} waypoints."
                            )

        # 6. Vérifier pinned_start/pinned_end
        for name, coureur in self.runners_data.items():
            for k, spec in enumerate(coureur.relais):
                if spec.pinned_start is not None:
                    if not (0 <= spec.pinned_start <= self.nb_points - 1):
                        raise ValueError(
                            f"❌ Relais {k} de '{name}' : pinned_start={spec.pinned_start} "
                            f"hors bornes [0, {self.nb_points - 1}]."
                        )
                if spec.pinned_end is not None:
                    if not (0 <= spec.pinned_end <= self.nb_points - 1):
                        raise ValueError(
                            f"❌ Relais {k} de '{name}' : pinned_end={spec.pinned_end} "
                            f"hors bornes [0, {self.nb_points - 1}]."
                        )

        # 7. Vérifier solo_max_m ≤ total_km
        total_m = self.total_km * 1000
        if self.solo_max_m > total_m:
            raise ValueError(
                f"❌ solo_max_km={self.solo_max_m/1000:.1f}km > parcours total={self.total_km:.1f}km.\n"
                f"   Réduire : solo_max_km ≤ {self.total_km:.1f}"
            )

        # 8. Vérifier night/no_solo intervals
        for intervals, name in [
            (self._intervals_night, "add_night"),
            (self._intervals_no_solo, "add_no_solo"),
        ]:
            for lo, hi in intervals:
                if lo > hi:
                    raise ValueError(
                        f"❌ {name}() : interval invalide (lo={lo} > hi={hi})."
                    )
                if not (0 <= lo <= self.nb_points - 1) or not (0 <= hi <= self.nb_points - 1):
                    raise ValueError(
                        f"❌ {name}() : interval hors bornes ({lo}, {hi}) "
                        f"pour {self.nb_points} waypoints."
                    )

    @property
    def runners(self) -> list[str]:
        return list(self.runners_data.keys())

    @property
    def paired_relays(self) -> list[tuple[str, int, str, int]]:
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

    def compat_score(self, r1: str, r2: str) -> int:
        return self.compat_matrix.get((r1, r2), 0)

    def _km_to_point(self, km: float) -> int:
        """Index du point le plus proche du km donné (sans effet de bord)."""
        best = 0
        best_d = abs(self.waypoints_km[0] - km)
        for i, wkm in enumerate(self.waypoints_km):
            d = abs(wkm - km)
            if d < best_d:
                best_d = d
                best = i
        return best

    def _hour_to_point(self, h: float, j: int = 0) -> int:
        """Index du point le plus proche de l'heure donnée (sans effet de bord)."""
        elapsed_h = h - self.start_hour + j * 24
        if elapsed_h < 0:
            elapsed_h += 24
        target_min = round(elapsed_h * 60)
        best = 0
        best_d = abs(self.cumul_temps[0] - target_min)
        for i, cm in enumerate(self.cumul_temps):
            d = abs(cm - target_min)
            if d < best_d:
                best_d = d
                best = i
        return best

    def _point_km(self, point: int) -> float:
        """km cumulé au point (index interne, après insertion des points de pause)."""
        return self.waypoints_km[point]

    def _point_hour(self, point: int) -> float:
        """Heure de passage au point (index interne, après insertion des points de pause),
        en heures depuis minuit jour 0."""
        return self.start_hour + self.cumul_temps[point] / 60.0

    # ------------------------------------------------------------------
    # Factory publique : Pin (épinglage d'un relais)
    # ------------------------------------------------------------------

    def new_pin(
        self,
        *,
        start_km: float | None = None,
        start_wp: int | None = None,
        start_time: "tuple[float, int] | None" = None,
        end_km: float | None = None,
        end_wp: int | None = None,
        end_time: "tuple[float, int] | None" = None,
    ) -> "Pin":
        """Crée un Pin (start, end) en indices de waypoints internes.

        start_km / start_wp / start_time : épingle le départ (mutuellement exclusifs).
        end_km   / end_wp   / end_time   : épingle l'arrivée (mutuellement exclusifs).
        """
        if sum(x is not None for x in (start_km, start_wp, start_time)) > 1:
            raise ValueError("new_pin() : start_km, start_wp et start_time sont mutuellement exclusifs.")
        if sum(x is not None for x in (end_km, end_wp, end_time)) > 1:
            raise ValueError("new_pin() : end_km, end_wp et end_time sont mutuellement exclusifs.")

        if start_km is not None:
            ps = self._km_to_point(start_km)
        elif start_wp is not None:
            ps = start_wp
        elif start_time is not None:
            h, j = start_time
            ps = self._hour_to_point(h, j)
        else:
            ps = None

        if end_km is not None:
            pe = self._km_to_point(end_km)
        elif end_wp is not None:
            pe = end_wp
        elif end_time is not None:
            h, j = end_time
            pe = self._hour_to_point(h, j)
        else:
            pe = None

        if ps is not None or pe is not None:
            self._arcs_frozen = True
        return Pin(ps, pe)

    # ------------------------------------------------------------------
    # Factories publiques : Interval (espace utilisateur → indices internes)
    # ------------------------------------------------------------------

    def interval_km(self, start_km: float | None = None, end_km: float | None = None) -> "Interval":
        """Interval défini par deux bornes kilométriques.

        Borne omise → premier (start) ou dernier (end) waypoint du parcours.
        """
        self._arcs_frozen = True
        lo = self._km_to_point(start_km) if start_km is not None else 0
        hi = self._km_to_point(end_km) if end_km is not None else self.nb_points - 1
        return Interval(lo, hi)

    def interval_time(
        self,
        start_h: float | None = None,
        start_j: int = 0,
        end_h: float | None = None,
        end_j: int = 0,
    ) -> "Interval":
        """Interval défini par deux bornes horaires (heure, jour).

        Borne omise → premier (start) ou dernier (end) waypoint du parcours.
        Les jours commencent à 0. Exemple : interval_time(22.5, 0, 3.5, 1)
        """
        self._arcs_frozen = True
        lo = self._hour_to_point(start_h, start_j) if start_h is not None else 0
        hi = self._hour_to_point(end_h, end_j) if end_h is not None else self.nb_points - 1
        return Interval(lo, hi)

    def interval_waypoints(self, start_wp: int | None = None, end_wp: int | None = None) -> "Interval":
        """Interval défini directement par des indices de waypoints.

        Borne omise → premier (start) ou dernier (end) waypoint du parcours.
        """
        self._arcs_frozen = True
        lo = start_wp if start_wp is not None else 0
        hi = end_wp if end_wp is not None else self.nb_points - 1
        return Interval(lo, hi)


    # ------------------------------------------------------------------
    # Sérialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Sérialise le Constraints en dict (sans I/O)."""
        _wpts, _profile = self.parcours.to_raw()
        return {
            "parcours_gpx": self.parcours.gpx_path,
            "waypoints": list(self._base_waypoints),   # sans les pauses
            "speed_kmh": self.speed_kmh,
            "start_hour": self.start_hour,
            "solo_max_m": self.solo_max_m,
            "defaults": self.defaults.to_dict(),
            "intervals_night": self._intervals_night,
            "intervals_no_solo": self._intervals_no_solo,
            "_profile_raw": _profile,
            "compat_matrix": {
                f"{a}|{b}": v
                for (a, b), v in self.compat_matrix.items()
                if a <= b
            },
            "pauses": [
                {"after_point": ap, "duree_heures": dh}
                for ap, dh in self._pauses
            ],
            "max_duos": [[r1, r2, nb] for r1, r2, nb in self.max_duos],
            "runners": {
                name: {
                    "relais": [s.to_dict() for s in cd.relais],
                    "options": cd.options.to_dict(),
                }
                for name, cd in self.runners_data.items()
            },
        }

    def to_json(self, filename: str) -> None:
        """Sérialise le Constraints dans un fichier JSON."""
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "Constraints":
        """Reconstruit un Constraints depuis un dict produit par to_dict()."""
        compat_matrix = {
            (a, b): v
            for key, v in data["compat_matrix"].items()
            for a, b in [key.split("|", 1)]
        }
        d = data["defaults"]
        parcours = Parcours.from_raw(data["waypoints"], data.get("_profile_raw"),
                                      gpx_path=data.get("parcours_gpx"))
        c = cls(
            parcours=parcours,
            speed_kmh=data["speed_kmh"],
            start_hour=data["start_hour"],
            compat_matrix=compat_matrix,
            solo_max_km=data["solo_max_m"] / 1000,
            solo_max_default=d["solo_max"],
            nuit_max_default=d["nuit_max"],
            repos_jour_heures=d["repos_jour_min"] / 60,
            repos_nuit_heures=d["repos_nuit_min"] / 60,
            max_same_partenaire=d["max_same_partenaire"],
        )
        # Rejoue les pauses
        for pause in data.get("pauses", []):
            c.add_pause(pause["duree_heures"], wp=pause["after_point"])
        # Recharge les intervalles nuit/solo
        if "intervals_night" in data:
            c._intervals_night = [tuple(iv) for iv in data["intervals_night"]]
        if "intervals_no_solo" in data:
            c._intervals_no_solo = [tuple(iv) for iv in data["intervals_no_solo"]]
        # Reconstruit runners_data directement (sans passer par le builder)
        for name, cd_data in data["runners"].items():
            coureur = Coureur(
                relais=[RelaySpec.from_dict(s) for s in cd_data["relais"]],
                options=RunnerOptions.from_dict(cd_data["options"]),
            )
            c.runners_data[name] = coureur
        c.max_duos = [tuple(entry) for entry in data.get("max_duos", [])]
        return c

    @classmethod
    def from_json(cls, filename: str) -> "Constraints":
        """Reconstruit un Constraints depuis un fichier JSON produit par to_json()."""
        with open(filename, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def print_summary(self) -> None:
        def _fmt_h(h: float) -> str:
            h = h % 24
            hh = int(h)
            mm = round((h - hh) * 60)
            return f"{hh}h{mm:02d}" if mm else f"{hh}h"

        def _fmt_intervals(intervals):
            parts = []
            for (lo, hi) in intervals:
                parts.append( f"{self._point_km(lo):0.1f}-{self._point_km(hi):0.1f}" )
            return "  ".join(parts)

        # --- Parcours ---
        print("Parcours : ")
        depart = _fmt_h(self.start_hour)
        print(f"  dist {self.total_km:.0f} km  vitesse {self.speed_kmh} km/h  départ {depart}")

        # --- Waypoints ---
        real_arcs = [km for i, km in enumerate(self.arc_km) if i not in self.pause_arcs]
        nb_real = len(real_arcs)
        moy = sum(real_arcs) / nb_real if nb_real else 0
        nb_lt1 = sum(1 for km in real_arcs if km < 0.3)
        nb_gt6 = sum(1 for km in real_arcs if km > 7.0)
        print(f"  segments {self.nb_arcs}  moyenne {moy:.2f} km/seg  max {max(real_arcs):.1f} km")
        print(f"  dont  {nb_lt1} <0.3km et  {nb_gt6} >7.0km")

        # --- Pauses ---
        if self._pauses:
            print("\nPauses :")
            for after_pt_user, duree_h in self._pauses:
                km = self._point_km(after_pt_user)
                h = self._point_hour(after_pt_user)
                print(f"  km {km:.1f}  ({_fmt_h(h)})  durée {duree_h:.1f}h")

        # --- Intervalles ---
        print("\nIntervalles (km):")
        if self._intervals_night:
            print(f"  nuits {_fmt_intervals(self._intervals_night)}")
        if self._intervals_no_solo:
            print(f"  solo interdit {_fmt_intervals(self._intervals_no_solo)}")


        # --- Coureurs ---
        print("\nCoureurs :")
        for r, coureur in self.runners_data.items():
            total_km = sum(spec.target_m for spec in coureur.relais) / 1000
            sizes = " + ".join(f"{spec.target_m/1000:.0f}" for spec in coureur.relais)
            print(f"  {r:<12}  {total_km:.0f} km  {sizes}")

        # --- Majorants ---
        ub = self.upper_bound
        if ub is not None:
            print("\nOptimum (estimé) :")
            print(f"  score duo max {ub.score}")
            print(f"  nb solos mini {ub.n_solos}")


        # --- Relais épinglés ---
        pinned = [
            (r, k, spec)
            for r, coureur in self.runners_data.items()
            for k, spec in enumerate(coureur.relais)
            if spec.pinned_start is not None or spec.pinned_end is not None
        ]
        if pinned:
            print("\nRelais épinglés :")
            for r, k, spec in pinned:
                parts = []
                if spec.pinned_start is not None:
                    parts.append(f"départ pt {spec.pinned_start} (km {self._point_km(spec.pinned_start):.1f})")
                if spec.pinned_end is not None:
                    parts.append(f"arrivée pt {spec.pinned_end} (km {self._point_km(spec.pinned_end):.1f})")
                print(f"  {r}[{k}]  {', '.join(parts)}")

        # --- Duos forcés ---
        pairs = self.paired_relays
        if pairs:
            print("\nDuos forcés :")
            for r1, k1, r2, k2 in pairs:
                print(f"  {r1}[{k1}] — {r2}[{k2}]")
