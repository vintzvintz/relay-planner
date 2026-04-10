# API de déclaration des contraintes (`relay`)

Ce document décrit l'API déclarative de `relay/constraints.py` utilisée dans `example.py`.

## Vue d'ensemble

La déclaration se fait en trois étapes :

1. Créer une instance `Constraints` (paramètres globaux du parcours)
2. Créer des coureurs via `c.new_runner()` → `RunnerBuilder`
3. Déclarer les relais de chaque coureur via `runner.add_relay()`

```python
from relay.constraints import Constraints, Preset

R15 = Preset(km=15, min=13, max=17)
R20 = Preset(km=20, min=15, max=21)

c = Constraints(parcours_gpx="gpx/parcours_avec_waypoints.gpx", speed_kmh=9.0,
                compat_matrix="compat_coureurs.xlsx", ...)

pascal = c.new_runner("Pascal", lvl=3)
pascal.add_relay(R20).add_relay(R15).add_relay(R15).add_relay(R15)
```

---

## `Constraints` — paramètres globaux

### Infos globales de la course

```python
c = Constraints(
    parcours_gpx="gpx/parcours_avec_waypoints.gpx",  # chemin GPX contenant waypoints et profil altimétrique
    speed_kmh=9.0,                        # vitesse de course en km/h
    start_hour=14.0,                      # heure de départ (h depuis minuit, jour 0)
    compat_matrix="compat_coureurs.xlsx", # chemin xlsx OU dict[tuple[str,str], int] — scores 0/1/2 (triangle inférieur)
    solo_max_km=17,                       # distance max d'un relais solo en km
)
```

### Valeurs par défaut par coureur

Ces paramètres s'appliquent à tous les coureurs sauf surcharge individuelle via `runner.set_options()`.

```python
c = Constraints(
    ...
    solo_max_default=1,        # nb max de solos par coureur
    nuit_max_default=2,        # nb max de relais de nuit par coureur
    repos_jour_heures=7,       # repos minimum entre deux relais (hors nuit), en heures
    repos_nuit_heures=9,       # repos minimum après un relais de nuit, en heures
    max_same_partenaire=3,     # int | None — nb max de binômes avec un même partenaire
)
```

Les durées de repos sont converties en minutes en interne (`repos_jour_min`, `repos_nuit_min`).

Les plages horaires nocturnes et solo-interdites sont déclarées séparément via `c.add_night()` et `c.add_no_solo()`.

---

## `Preset` — gabarit de taille de relais

```python
from relay.constraints import Preset

R10   = Preset(km=10, min=8,  max=13)
R13_F = Preset(km=13, min=8,  max=15)
R15   = Preset(km=15, min=13, max=17)
R20   = Preset(km=20, min=15, max=21)
R30   = Preset(km=30, min=25, max=31)
```

Un `Preset` encode une distance cible et des bornes min/max. Contrairement au modèle uniforme,
il n'y a pas de constantes prédéfinies dans le package — chaque `example.py` déclare les siennes.

---

## `c.add_pause()` — déclarer une pause planifiée

Doit être appelé **avant** toute factory `interval_*()`. Retourne `self` (chaînable).

```python
# Position par km (waypoint le plus proche)
c.add_pause(duree_heures=1.8, km=250)

# Position par indice de waypoint (espace utilisateur)
c.add_pause(duree_heures=0, wp=154)  # 0h = point de relais obligatoire sans pause

# Position par heure de passage
c.add_pause(duree_heures=1.5, heure=3.5, jour=1)  # 3h30 le lendemain du départ
```

Les trois paramètres de position (`wp=`, `km=`, `heure=`+`jour=`) sont mutuellement exclusifs.
Insère un arc de 0 km et de durée non nulle entre le point choisi et le suivant.
Tous les `cumul_temps` suivants sont décalés. L'arc de pause est stocké dans `c.pause_arcs`
et exclu de la contrainte de couverture.

---

## `c.add_night()` — déclarer les plages horaires nocturnes

Retourne `self` (chaînable). Peut être appelée plusieurs fois pour plusieurs intervalles.

```python
c.add_night(c.interval_time(start_h=23.5, start_j=0, end_h=6.0, end_j=1))
c.add_night(c.interval_time(start_h=23.5, start_j=1, end_h=6.0, end_j=2))
```

Un relais est considéré de nuit s'il chevauche au moins un intervalle déclaré.


---

## `c.add_no_solo()` — déclarer les zones où les solos sont interdits

Retourne `self` (chaînable). Peut être appelée plusieurs fois pour plusieurs intervalles.

```python
c.add_no_solo(c.interval_time(start_h=23.5, start_j=0, end_h=7.0, end_j=1))
c.add_no_solo(c.interval_time(start_h=23.5, start_j=1, end_h=7.0, end_j=2))
```

Un relais ne peut pas être solo s'il chevauche l'une de ces zones.

---

## `c.new_runner()` — créer un coureur

```python
runner = c.new_runner(name, lvl)
# name : str — identifiant unique du coureur (doit exister dans compat_matrix)
# lvl  : int — niveau du coureur, poids dans l'objectif D+/D- (--dplus)
```

Retourne un `RunnerBuilder`.

### `set_options`

```python
runner.set_options(
    *,
    solo_max=None,            # int | None — surcharge solo_max_default
    nuit_max=None,            # int | None — surcharge nuit_max_default
    repos_jour=None,          # float | None — surcharge repos_jour en heures
    repos_nuit=None,          # float | None — surcharge repos_nuit en heures
    max_same_partenaire=None, # int | None — surcharge la limite globale pour ce coureur
) -> RunnerBuilder
```

---

## `runner.add_relay()` — déclarer un ou plusieurs relais

```python
runner.add_relay(
    *presets,           # un ou plusieurs Preset ou SharedLeg (arguments positionnels)
    window=None,        # Interval | list[Interval] | None — fenêtre de placement
    # Épinglage du départ du premier relais (un seul à la fois) :
    start_km=None,      # float | None — épingle au waypoint le plus proche du km
    start_wp=None,      # int   | None — épingle à l'indice de waypoint
    start_time=None,    # tuple[float, int] | None — épingle à (heure, jour)
    # Épinglage de l'arrivée du dernier relais (un seul à la fois) :
    end_km=None,
    end_wp=None,
    end_time=None,
    dplus_max=None,     # int | None — limite D+ + D- en mètres (requiert profil altimétrique dans parcours_gpx)
    solo=None,          # bool | None — True=solo obligatoire, False=binôme obligatoire, None=libre (ignoré pour SharedLeg)
)
```

Retourne `self` pour le chaînage.

Un seul preset = relais simple. Plusieurs presets = relais enchaînés sans repos entre eux (`end[k] == start[k+1]`).

### Paramètre `presets`

```python
# Relais simple
runner.add_relay(R10)

# Via SharedLeg (binôme forcé)
shared = c.new_shared_relay(R30)
runner1.add_relay(shared, window=nuit1_30k)
runner2.add_relay(shared, window=nuit1_30k)

# Séquence chaînée (2 relais enchaînés)
quentin.add_relay(R15, shared_nuit, window=dispo_quentin)
martin.add_relay(shared_nuit, R10, window=dispo_quentin)
```

### Paramètre `window`

Restreint le départ et l'arrivée du relais à une plage de points. Utiliser les factories de `Constraints` :

```python
j1 = c.interval_time(end_h=15.0, end_j=1)      # jusqu'à 15h le lendemain
runner.add_relay(R20, window=j1)

fin = c.interval_km(start_km=400)              # seulement après 400 km
runner.add_relay(R10, window=fin)
```

### Épinglage départ / arrivée

Fixe un point de départ ou d'arrivée de façon indépendante (premier/dernier relais en cas de chaînage) :

```python
arthur.add_relay(R10, start_km=0)             # départ fixé au km 0
arthur.add_relay(R10, start_time=(14.0, 0))   # départ fixé à 14h jour 0
oscar.add_relay(R10, end_wp=c.last_point)   # arrivée fixée au dernier waypoint
```

### Paramètre `dplus_max`

Limite D+ + D− en mètres sur ce relais. Requiert un profil altimétrique dans le GPX passé à `parcours_gpx=` :

```python
nadine.add_relay(R10, dplus_max=600)   # D+ + D- ≤ 600 m
nadine.add_relay(R10, R10, dplus_max=600)   # D+ + D- ≤ 600 m par relais individuel
```

### Paramètre `solo`

Force le statut solo/binôme d'un relais (appliqué aux `Preset`, ignoré pour les `SharedLeg`) :

```python
runner.add_relay(R10, solo=True)     # ce relais DOIT être en solo
runner.add_relay(R15, solo=False)    # ce relais DOIT être en binôme
runner.add_relay(R15)                # solo=None (défaut) — le solveur choisit
```

`solo=True` est incompatible avec `SharedLeg` (lever `ValueError`).

---

## `c.add_max_duos()` — limiter les binômes entre deux coureurs

```python
c.add_max_duos(runner1: RunnerBuilder, runner2: RunnerBuilder, nb: int) -> None
```

```python
c.add_max_duos(gaelle, nadine, nb=1)   # au plus 1 binôme entre gaelle et nadine
```

---

## `c.new_shared_relay()` — créer un relais partagé (binôme forcé)

```python
shared = c.new_shared_relay(preset)
# ou avec des bornes explicites :
shared = c.new_shared_relay(target_km=30, min_km=25, max_km=31)
```

Passer la même instance à `add_relay()` de deux coureurs pour les forcer à courir ensemble.
Un `SharedLeg` ne peut être partagé qu'entre exactement 2 coureurs — vérifié au moment de `build_model()`
via `c.validate()`. Toutes les instances créées par `new_shared_relay()` sont suivies dans `c._shared_legs`.

---

## `Interval` — plage de points

```python
from relay.constraints import Interval  # NamedTuple(lo, hi)

# Ne pas instancier directement. Utiliser les factories de Constraints :
window = c.interval_km(start_km=0, end_km=250)
window = c.interval_time(start_h=22.5, start_j=0, end_h=3.5, end_j=1)
window = c.interval_waypoints(start_wp=0, end_wp=80)
```

Les bornes omises prennent la valeur extrême du parcours (début ou fin).
Les factories peuvent aussi prendre une seule borne :
```python
c.interval_time(end_h=15.0, end_j=1)   # du début jusqu'à 15h le lendemain
c.interval_km(start_km=300)             # de 300 km jusqu'à la fin
```

Appeler les factories **après** tous les `add_pause()` (elles gèlent les indices internes).

---

## Méthodes utilitaires de `Constraints`

### Factories d'intervalles

```python
c.interval_km(start_km, end_km) -> Interval
c.interval_time(start_h, start_j, end_h, end_j) -> Interval
c.interval_waypoints(start_wp, end_wp) -> Interval
```

### Conversions (méthodes privées, usage interne)

```python
c._km_to_point(km) -> int        # index du point le plus proche du km donné
c._hour_to_point(h, j=0) -> int  # index du point le plus proche de l'heure donnée (+ j jours)
```

```python
# Exemples dans add_pause() ou pinning :
c.add_pause(duree_heures=1.8, km=250)
arthur.add_relay(R10, start_time=(14.0, 0))
```

### Propriétés dérivées

| Propriété              | Type                          | Description                                              |
|------------------------|-------------------------------|----------------------------------------------------------|
| `c.runners`            | `list[str]`                   | Noms des coureurs dans l'ordre de déclaration            |
| `c.paired_relays`      | `list[tuple[str,int,str,int]]`| Tous les pairings `(r1,k1,r2,k2)` déclarés              |
| `c._intervals_night`   | `list[tuple[int,int]]`        | Intervalles (wp_debut, wp_fin) nocturnes                 |
| `c._intervals_no_solo` | `list[tuple[int,int]]`        | Intervalles (wp_debut, wp_fin) solo-interdits            |
| `c.last_point`         | `int`                         | `nb_points - 1` — borne supérieure pour les intervals    |
| `c.nb_points`          | `int`                         | Nombre total de points (y compris points de pause)       |
| `c.nb_arcs`            | `int`                         | Nombre total d'arcs (y compris arcs de pause)            |
| `c.pause_arcs`         | `set[int]`                    | Indices des arcs de pause (exclus de la couverture)      |
| `c.cumul_m`            | `list[int]`                   | Distances cumulatives en mètres                          |
| `c.cumul_temps`        | `list[int]`                   | Temps cumulatifs en minutes depuis le départ             |
| `c.upper_bound`        | `UpperBound \| None`          | Majorant heuristique du score (taille=target) — lazy     |
| `c.upper_bound_max`    | `UpperBound \| None`          | Majorant garanti du score (taille=max_m) — lazy          |
| `c.cumul_dplus`        | `tuple[list[int], list[int]] \| None` | Tables (cumul_dp, cumul_dm) en mètres — lazy    |

### Compatibilité

```python
c.compat_score(r1, r2) -> int   # 0, 1 ou 2
```

### Vérification et diagnostic

```python
c.print_summary()   # Affiche le résumé (points, arcs, coureurs, arcs nocturnes)
```

### Sérialisation

```python
c.to_dict() -> dict            # sérialise en dict (sans I/O)
c.to_json(filename)            # sauvegarde en JSON
Constraints.from_dict(data)    # reconstruit depuis un dict
Constraints.from_json(path)    # charge depuis un fichier JSON
```

`waypoints` est sérialisé **sans** les points de pause insérés par `add_pause()` : `from_dict()` rejoue
les pauses depuis le champ `pauses`, évitant une double-insertion lors d'un round-trip.

---

## Structures internes (lecture seule)

### `RelaySpec`

```python
@dataclass
class RelaySpec:
    target_m: int                          # distance cible en mètres
    min_m: int | None                      # distance minimale en mètres
    max_m: int | None                      # distance maximale en mètres
    paired_with: tuple[str, int] | None    # (runner_name, relay_index) si binôme forcé
    window: list[tuple[int, int]] | None   # intervalles de placement (indices de points)
    pinned_start: int | None               # point de départ fixé (None = libre)
    pinned_end: int | None                 # point d'arrivée fixé (None = libre)
    dplus_max: int | None                  # limite D+ + D- en mètres
    solo: bool | None                      # True=solo obligatoire, False=binôme obligatoire, None=libre
```

### `RunnerOptions`

```python
@dataclass
class RunnerOptions:
    solo_max: int | None = None
    nuit_max: int | None = None
    repos_jour_min: int | None = None   # en minutes
    repos_nuit_min: int | None = None   # en minutes
    max_same_partenaire: int | None = None
    lvl: int | None = None              # niveau coureur — initialisé par new_runner(name, lvl)
```

---

## Exemple complet minimal

```python
from relay.constraints import Constraints, Preset
from relay import solve

R10 = Preset(km=10, min=8,  max=13)
R15 = Preset(km=15, min=13, max=17)
R30 = Preset(km=30, min=25, max=31)

c = Constraints(
    parcours_gpx="gpx/parcours_avec_waypoints.gpx",
    speed_kmh=9.0, start_hour=14.0,
    compat_matrix="compat_coureurs.xlsx",
    solo_max_km=17, solo_max_default=1, nuit_max_default=2,
    repos_jour_heures=7, repos_nuit_heures=9,
    max_same_partenaire=None,
)

# Pauses et plages nuit/solo (avant les factories d'Interval et new_runner)
c.add_pause(duree_heures=1.8, km=250)
c.add_night(c.interval_time(start_h=23.5, start_j=0, end_h=6.0, end_j=1))
c.add_night(c.interval_time(start_h=23.5, start_j=1, end_h=6.0, end_j=2))
c.add_no_solo(c.interval_time(start_h=23.5, start_j=0, end_h=7.0, end_j=1))
c.add_no_solo(c.interval_time(start_h=23.5, start_j=1, end_h=7.0, end_j=2))

# Fenêtres de disponibilité
nuit1 = c.interval_time(start_h=22.5, start_j=0, end_h=3.5, end_j=1)
nuit2 = c.interval_time(start_h=22.5, start_j=1, end_h=3.5, end_j=2)
j1    = c.interval_time(end_h=15.0, end_j=1)

# Relais partagé (binôme obligatoire)
relay_nuit = c.new_shared_relay(R30)

# Coureurs
alice = c.new_runner("Alice", lvl=4).set_options(nuit_max=3)
alice.add_relay(R15).add_relay(R15).add_relay(R15).add_relay(relay_nuit, window=nuit1)

bob = c.new_runner("Bob", lvl=3).set_options(solo_max=0)
bob.add_relay(relay_nuit, window=nuit1).add_relay(R10).add_relay(R10)

carol = c.new_runner("Carol", lvl=2)
carol.add_relay(R10, window=j1, dplus_max=600).add_relay(R15).add_relay(R15)

solve(c)
```

---

## Vérification post-résolution (`relay.check`)

```python
from relay import check

ok = check(solution)               # affiche sur stdout, retourne bool
ok = check(solution, out=my_file)  # redirige la sortie
```

`check()` est appelé **automatiquement** par `Solution.from_cpsat()` et `Solution.from_dict()` / `from_json()`.
Il couvre :

| Vérification           | Ce qui est testé                                                                   |
|------------------------|------------------------------------------------------------------------------------|
| Couverture             | Chaque arc non-pause couvert exactement 1 ou 2 fois                                |
| Pauses                 | Aucun relais ne traverse un arc de pause                                           |
| Tailles relais         | Distance dans `[min_m, max_m]` pour chaque relais                                 |
| Repos                  | Gap temporel ≥ `repos_jour_min` ou `repos_nuit_min` entre relais consécutifs       |
| Nuit max               | Nombre de relais nocturnes ≤ `nuit_max` par coureur                                |
| Solo max               | Nombre de relais solo ≤ `solo_max` par coureur                                     |
| Solo zone              | Pas de relais solo **chevauchant** une zone interdite (même sémantique que le modèle)      |
| No-overlap             | Pas de chevauchement entre coureurs différents hors binômes                        |
| Pairings               | Les `SharedLeg` sont bien respectés dans la solution                               |
| Compatibilité          | Tous les binômes actifs ont un score > 0                                           |
| Max duos               | Nombre de binômes ≤ limite déclarée par `add_max_duos()`                           |
| Solo forcé             | Relais `solo=True` en solo, relais `solo=False` en binôme                          |
