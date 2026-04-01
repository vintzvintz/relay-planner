# API de déclaration des contraintes

Ce document décrit l'API déclarative de `relay/constraints.py` utilisée dans `example.py` pour définir le problème d'optimisation.

## Vue d'ensemble

La déclaration se fait en trois étapes :

1. Créer une instance `Constraints` (paramètres globaux du parcours)
2. Créer des coureurs via `c.new_runner()` → `RunnerBuilder`
3. Déclarer les relais de chaque coureur via `runner.add_relay()`

```python
from relay import Constraints, Intervals, R20, R15

c = Constraints(total_km=440, nb_segments=176, ...)

pierre = c.new_runner("Pierre")
pierre.add_relay(R20).add_relay(R15, nb=3)
```

---

## `Constraints` — paramètres globaux

```python
c = Constraints(
    total_km=440,           # distance totale en km
    nb_segments=176,        # nombre de segments (0-indexés) — valeurs courantes : 440=1k, 290=1k5, 220=2k, 176=2k5, 135=3k3
    speed_kmh=9.0,          # vitesse de course en km/h
    start_hour=15.0,        # heure de départ (h depuis minuit, jour 0)
    compat_matrix=COMPAT_MATRIX,  # dict[tuple[str,str], int] — scores 0/1/2 (triangle inférieur)
    solo_max_km=17,         # taille max d'un relais solo en km
    solo_max_default=1,     # nb max de solos par coureur (défaut)
    nuit_max_default=1,     # nb max de relais de nuit par coureur (défaut)
    repos_jour_heures=7,    # repos minimum entre deux relais (hors nuit), en heures
    repos_nuit_heures=9,    # repos minimum après un relais de nuit, en heures
    nuit_debut=0,           # heure de début de la plage nuit — détermine repos_nuit (défaut : 0h)
    nuit_fin=6,             # heure de fin de la plage nuit (défaut : 6h)
    solo_autorise_debut=None,  # heure de début de la plage où les solos sont autorisés (défaut : None → égal à nuit_debut)
    solo_autorise_fin=None,    # heure de fin de la plage où les solos sont autorisés (défaut : None → égal à nuit_fin)
    max_same_partenaire=None,  # int | None — nb max de binômes avec un même partenaire (global)
    enable_flex=True,       # si False, les types flex (R13_F, R15_F) sont traités comme fixes
    allow_flex_flex=True,   # si False, deux coureurs flex en binôme sont chacun forcés à leur taille nominale (pas de réduction double-flex)
    profil_csv=None,        # str | None — chemin vers gpx/altitude.csv pour les D+/D− (chargé en lazy)
)
```

Les durées de repos sont converties en nombre de segments via `duration_to_segs()` (arrondi au supérieur).

---

## `c.add_pause()` — déclarer une pause planifiée

Permet de déclarer des **pauses planifiées** (arrêt complet de la course) pendant le parcours.
Doit être appelé **avant** tout `new_runner()`, et dans l'ordre croissant de `seg`.

```python
c.add_pause(
    seg=c.hour_to_seg(16.0, jour=1),  # segment après lequel la course s'arrête
    duree=1.5,                         # durée de la pause en heures
)
```

Paramètres :
- `seg` : numéro de segment après lequel la course s'arrête ; utiliser `hour_to_seg()` ou `km_to_seg()` pour obtenir ce numéro
- `duree` : durée de la pause en heures (doit être > 0)

La durée de la pause est opaque pour le reste de la déclaration : `hour_to_seg()` et `km_to_seg()` tiennent compte des pauses déjà déclarées et retournent toujours des numéros de segments de course.

---

## `c.new_runner()` — créer un coureur

```python
runner = c.new_runner(name)   # str — identifiant unique du coureur (doit exister dans la matrice de compat)
```

Retourne un `RunnerBuilder`. Les options individuelles du coureur sont définies via `set_options()` (voir ci-dessous).

### Méthode `set_options`

```python
runner.set_options(
    *,
    solo_max=None,          # int | None — surcharge solo_max_default
    nuit_max=None,          # int | None — surcharge nuit_max_default
    repos_jour=None,        # float | None — surcharge repos_jour en heures
    repos_nuit=None,        # float | None — surcharge repos_nuit en heures
    max_same_partenaire=None,  # int | None — surcharge la limite globale pour ce coureur
) -> RunnerBuilder
```

Retourne `self` pour le chaînage.

**Exemples :**
```python
alexis   = c.new_runner("Alexis").set_options(nuit_max=5)
vincent  = c.new_runner("Vincent").set_options(repos_jour=6, repos_nuit=8)
leo      = c.new_runner("Leo").set_options(solo_max=0)   # interdit de solo
alexis.set_options(max_same_partenaire=2)   # alexis court au max 2 fois avec le même partenaire
```

---

## `runner.add_relay()` — déclarer un relais

```python
runner.add_relay(
    size,           # str (constante de type : R10, R15, …) ou SharedLeg (voir ci-dessous)
    *,
    nb=1,           # int — nombre de relais identiques à ajouter (ignoré pour SharedLeg)
    window=None,    # Intervals | tuple[int,int] | None — fenêtre de placement
    pinned=None,    # int | None — segment de départ fixé
)
```

Retourne `self` pour le chaînage.

### Paramètre `size`

Un **nom de type** (`str`) importé de `relay`, ou un `SharedLeg` :

| Constante | Distance approx. | Segments (flex off) | Segments (flex on) |
|-----------|------------------|---------------------|--------------------|
| `R10`     | ~10 km           | `{3}`               | `{3}`              |
| `R15`     | ~15 km           | `{5}`               | `{5}`              |
| `R20`     | ~20 km           | `{6}`               | `{6}`              |
| `R30`     | ~30 km           | `{9}`               | `{9}`              |
| `R13_F`   | 10–13 km         | `{4}`               | `{3, 4}`           |
| `R15_F`   | 10–15 km         | `{5}`               | `{3, 4, 5}`        |

Le nombre exact de segments dépend de `nb_segments` et `total_km` (calculé par `make_relay_types()`).

- **Singleton** : taille fixe, le relais couvre exactement `n` segments.
- **Multi-valeurs** (flex on) : relais flexible — le solveur choisit la taille dans l'ensemble. Le coureur partenaire impose sa taille dans le cas d'un binôme.

### Paramètre `window`

Restreint le segment de départ à une ou plusieurs plages, exprimées en numéros de segments de course :

```python
# Fenêtre prédéfinie — hour_to_seg() retourne un numéro de segment
j1 = Intervals([(0, c.hour_to_seg(15.0, jour=1))])
runner.add_relay(R20, window=j1)

# Borne "jusqu'à la fin" — utiliser last_active_seg
fin = Intervals([(c.hour_to_seg(9, jour=2), c.last_active_seg)])
runner.add_relay(R10, window=fin)

# Fenêtre calculée automatiquement (toutes les nuits)
girls_night = c.night_windows()
runner.add_relay(R10, window=girls_night)

# Tuple direct (start_seg, end_seg) — équivalent à un Intervals à un seul intervalle
runner.add_relay(R10, window=(0, 20))
```

### Paramètre `pinned`

Fixe le segment de départ exactement, en numéro de segment de course :

```python
alexis.add_relay(R10, pinned=0)                                       # premier segment
olivier.add_relay(R10, pinned=c.last_active_seg - c.size_of(R10))    # dernier relais possible
pierre.add_relay(R20, pinned=c.size_of(R10))                          # juste après un 10 km
```

Incompatible avec un `size` flexible (`len(size) > 1`).

---

## `c.add_max_binomes()` — limiter les binômes entre deux coureurs

```python
c.add_max_binomes(runner1: RunnerBuilder, runner2: RunnerBuilder, nb: int) -> None
```

Limite à au plus `nb` binômes entre `runner1` et `runner2` sur l'ensemble du planning.
Stocké dans `c.once_max` comme `(name1, name2, nb)` et pris en compte par le modèle CP-SAT.

```python
alexis  = c.new_runner("Alexis")
olivier = c.new_runner("Olivier")
c.add_max_binomes(alexis, olivier, 1)   # au plus 1 binôme ensemble
```

---

## `c.new_relay()` — créer un relais partagé (binôme forcé)

```python
shared = c.new_relay(size)   # size : str (constante de type, ex. R30)
```

Crée un `SharedLeg` à passer à `add_relay()` de **deux coureurs** pour les forcer à courir ensemble sur ce relais.

```python
nuit1 = c.new_relay(R30)

alexis.add_relay(nuit1, window=nuit1_30k)
olivier.add_relay(nuit1, window=nuit1_30k)
# → alexis et olivier forment un binôme obligatoire sur ce relais de nuit
```

Contrainte : un `SharedLeg` ne peut être partagé qu'entre exactement 2 coureurs.

---

## `Intervals` — plages de segments

```python
from relay import Intervals

# Un ou plusieurs intervalles [start, end] inclus (en numéros de segments)
window = Intervals([(start1, end1), (start2, end2), ...])
```

Utilisé pour les fenêtres de placement (`window=`) et les disponibilités coureurs.

---

## Méthodes utilitaires de `Constraints`

### Conversions

```python
c.hour_to_seg(hour, jour=0) -> int
```
Convertit une heure absolue (+ décalage en jours) en numéro de segment. Utilisable dans `window=`, `pinned=` ou `add_pause()`.

```python
c.hour_to_seg(23.5)          # 23h30 le jour de départ
c.hour_to_seg(4, jour=1)     # 4h00 le lendemain
c.hour_to_seg(11, jour=2)    # 11h00 deux jours après le départ
```

```python
c.km_to_seg(km) -> int
```
Convertit une distance en km en numéro de segment (arrondi au bas). Utilisable dans `add_pause(seg=...)`, `window=` ou `pinned=`.

```python
c.size_of(relay_name) -> int
```
Retourne la taille en segments du type de relais (lève `ValueError` si le type est flexible).

```python
c.duration_to_segs(hours) -> int
```
Convertit une durée en heures en nombre de segments (arrondi au supérieur).

```python
c.segment_start_hour(seg) -> float
```
Retourne l'heure de début du segment `seg` en heures depuis minuit. Destiné principalement à l'affichage des solutions.

### Fenêtres nocturnes

```python
c.night_windows() -> Intervals
```
Retourne un `Intervals` couvrant toutes les plages nocturnes (`nuit_debut`–`nuit_fin`) sur l'ensemble du parcours.

### Compatibilité

```python
c.compat_score(r1, r2) -> int     # 0, 1 ou 2
```

`is_compatible()` a été supprimé — utiliser `c.compat_score(r1, r2) > 0` à la place.

### Propriétés dérivées

| Propriété              | Type                          | Description                                                     |
|------------------------|-------------------------------|-----------------------------------------------------------------|
| `c.runners`            | `list[str]`                   | Noms des coureurs dans l'ordre de déclaration                   |
| `c.relay_sizes`        | `dict[str, list[int]]`        | Taille nominale (`max(size)`) de chaque relais par coureur      |
| `c.defaults`           | `RunnerOptions`               | Valeurs par défaut globales (repos, solo_max, nuit_max, …)      |
| `c.night_segments`     | `set[int]`                    | Ensemble des numéros de segments de nuit                        |
| `c.segment_km`         | `float`                       | Longueur d'un segment en km                                     |
| `c.segment_duration`   | `float`                       | Durée d'un segment en heures                                    |
| `c.paired_relays`      | `list[tuple[str,int,str,int]]`| Tous les pairings `(r1,k1,r2,k2)` déclarés                     |
| `c.solo_max_size`      | `int`                         | Taille max d'un solo en segments                                |
| `c.has_flex`           | `bool`                        | `True` si au moins un relais a une taille variable              |
| `c.last_active_seg`    | `int`                         | Borne supérieure pour les `Intervals` et `pinned` — à utiliser comme borne "jusqu'à la fin" |

### Vérification et diagnostic

```python
c.print_summary()   # Affiche le résumé complet (coureurs, compat, relais épinglés, borne LP)
```

La borne LP est calculée à la demande via la propriété `c.lp_bounds` (lazy, mémorisée). `print_summary()` l'utilise automatiquement. Le résultat expose :
- `c.lp_bounds.upper_bound` (`int`) : borne supérieure arrondie
- `c.lp_bounds.solo_nb` (`float`) : nombre de solos estimé par la relaxation LP
- `c.lp_bounds.solo_km` (`float`) : km en solo estimés par la relaxation LP

### Sérialisation

```python
c.to_dict() -> dict          # sérialise en dict (sans I/O)
c.to_json(filename)          # sauvegarde en JSON
Constraints.from_dict(data)  # reconstruit depuis un dict
Constraints.from_json(path)  # charge depuis un fichier JSON
```

Le JSON produit contient les contraintes complètes (coureurs, relais, pauses, compat_matrix) et permet de reconstruire un `Constraints` identique sans l'`example.py` d'origine. `relay_types` n'est pas sérialisé car redondant — les tailles sont stockées directement en segments dans chaque `RelaySpec`.

---

## Structures internes (lecture seule)

### `RelaySpec`

Descripteur d'un relais enregistré dans `Coureur.relais` :

```python
@dataclass
class RelaySpec:
    size: set[int]                          # tailles permises (segments)
    paired_with: tuple[str, int] | None     # (runner_name, relay_index) si binôme forcé
    window: list[tuple[int, int]] | None    # intervalles de placement autorisés
    pinned: int | None                      # segment de départ fixé
```

Supporte `to_dict()` / `from_dict()`.

### `RunnerOptions`

Options individuelles d'un coureur (ou valeurs par défaut globales dans `Constraints.defaults`) :

```python
@dataclass
class RunnerOptions:
    solo_max: int | None = None
    nuit_max: int | None = None
    repos_jour: int | None = None    # en segments
    repos_nuit: int | None = None    # en segments
    max_same_partenaire: int | None = None
```

Supporte `to_dict()` / `from_dict()`.

### `Coureur`

Contraintes résumées d'un coureur :

```python
@dataclass
class Coureur:
    relais: list[RelaySpec]
    options: RunnerOptions   # initialisé depuis Constraints.defaults, écrasé par set_options()
```

---

## Exemple complet minimal

```python
from relay import Constraints, Intervals, R20, R15, R15_F, R30, solve
from compat import COMPAT_MATRIX

c = Constraints(
    total_km=440, nb_segments=176, speed_kmh=9.0, start_hour=15.0,
    compat_matrix=COMPAT_MATRIX,
    solo_max_km=17, solo_max_default=1, nuit_max_default=1,
    repos_jour_heures=7, repos_nuit_heures=9,
    enable_flex=True,
)

# Pause optionnelle (doit être déclarée avant new_runner)
# c.add_pause(seg=c.hour_to_seg(16.0, jour=1), duree=1.5)  # j1 16h00, durée 1h30

# Plages temporelles
j1       = Intervals([(0, c.hour_to_seg(15.0, jour=1))])
fin      = Intervals([(c.hour_to_seg(9, jour=2), c.last_active_seg)])  # jusqu'à la fin
nuit     = c.night_windows()

# Relais partagé (binôme obligatoire)
relay_nuit = c.new_relay(R30)

# Coureurs
alice = c.new_runner("Alice").set_options(nuit_max=2)
alice.add_relay(R20, nb=2).add_relay(R15_F, window=j1)

bob = c.new_runner("Bob").set_options(solo_max=0)
bob.add_relay(relay_nuit, window=nuit).add_relay(R15, nb=3)

carol = c.new_runner("Carol")
carol.add_relay(relay_nuit, window=nuit).add_relay(R15, pinned=0)

solve(c)
```
