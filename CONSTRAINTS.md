# API de déclaration des contraintes

Ce document décrit l'API déclarative de `constraints.py` utilisée dans `data.py` pour définir le problème d'optimisation.

## Vue d'ensemble

La déclaration se fait en trois étapes :

1. Créer une instance `RelayConstraints` (paramètres globaux du parcours)
2. Créer des coureurs via `c.new_runner()` → `RunnerBuilder`
3. Déclarer les relais de chaque coureur via `runner.add_relay()`

```python
from constraints import RelayConstraints, RelayIntervals, R20, R15

c = RelayConstraints(total_km=440, nb_segments=290, ...)

pierre = c.new_runner("Pierre")
pierre.add_relay(R20).add_relay(R15, nb=3)
```

---

## `RelayConstraints` — paramètres globaux

```python
c = RelayConstraints(
    total_km=440,           # distance totale en km
    nb_segments=290,        # nombre de segments (0-indexés) — valeurs courantes : 440=1k, 290=1k5, 220=2k, 135=3k3
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
)
```

Les durées de repos sont converties en segments via `duration_to_segs()` (arrondi au supérieur).

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
    size,           # str (constante de type : R10, R15, …) ou SharedRelay (voir ci-dessous)
    *,
    nb=1,           # int — nombre de relais identiques à ajouter (ignoré pour SharedRelay)
    window=None,    # RelayIntervals | tuple[int,int] | None — fenêtre de placement
    pinned=None,    # int | None — segment de départ fixé
)
```

Retourne `self` pour le chaînage.

### Paramètre `size`

Un **nom de type** (`str`) importé de `constraints.py`, ou un `SharedRelay` :

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

Restreint le segment de départ à une ou plusieurs plages :

```python
# Fenêtre prédéfinie
j1 = RelayIntervals([(0, c.hour_to_seg(15.0, jour=1))])
runner.add_relay(R20, window=j1)

# Fenêtre calculée automatiquement (toutes les nuits)
girls_night = c.night_windows()
runner.add_relay(R10, window=girls_night)

# Tuple direct (start_seg, end_seg) — équivalent à un RelayIntervals à un seul intervalle
runner.add_relay(R10, window=(0, 20))
```

### Paramètre `pinned`

Fixe le segment de départ exactement :

```python
alexis.add_relay(R10, pinned=0)                      # premier relais
olivier.add_relay(R10, pinned=c.nb_segments - 3)     # dernier relais
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

Crée un `SharedRelay` à passer à `add_relay()` de **deux coureurs** pour les forcer à courir ensemble sur ce relais.

```python
nuit1 = c.new_relay(R30)

alexis.add_relay(nuit1, window=nuit1_30k)
olivier.add_relay(nuit1, window=nuit1_30k)
# → alexis et olivier forment un binôme obligatoire sur ce relais de nuit
```

Contrainte : un `SharedRelay` ne peut être partagé qu'entre exactement 2 coureurs.

---

## `RelayIntervals` — plages de segments

```python
from constraints import RelayIntervals

# Un ou plusieurs intervalles [start, end] inclus (en numéros de segments)
window = RelayIntervals([(start1, end1), (start2, end2), ...])
```

Utilisé pour les fenêtres de placement (`window=`) et les disponibilités coureurs.

---

## Méthodes utilitaires de `RelayConstraints`

### Conversions temporelles

```python
c.hour_to_seg(hour, jour=0) -> int
```
Convertit une heure absolue (+ décalage en jours) en numéro de segment (tronqué).

```python
c.hour_to_seg(23.5)          # 23h30 le jour de départ
c.hour_to_seg(4, jour=1)     # 4h00 le lendemain
c.hour_to_seg(11, jour=2)    # 11h00 deux jours après le départ
```

```python
c.duration_to_segs(hours) -> int
```
Convertit une durée en heures en nombre de segments (arrondi au supérieur).

```python
c.segment_start_hour(seg) -> float
```
Retourne l'heure de début du segment (en heures depuis minuit mercredi).

### Fenêtres nocturnes

```python
c.night_windows() -> RelayIntervals
```
Retourne un `RelayIntervals` couvrant toutes les plages nocturnes (`nuit_debut`–`nuit_fin`) sur l'ensemble du parcours.

### Compatibilité

```python
c.is_compatible(r1, r2) -> bool   # True si compat_score > 0
c.compat_score(r1, r2) -> int     # 0, 1 ou 2
```

### Propriétés dérivées

| Propriété              | Type                          | Description                                      |
|------------------------|-------------------------------|--------------------------------------------------|
| `c.runners`            | `list[str]`                   | Noms des coureurs dans l'ordre de déclaration    |
| `c.relay_sizes`        | `dict[str, list[int]]`        | Taille nominale (`max(size)`) de chaque relais   |
| `c.runner_nuit_max`    | `dict[str, int]`              | Nb max de relais de nuit par coureur (résolu)    |
| `c.runner_solo_max`    | `dict[str, int]`              | Nb max de solos par coureur (résolu)             |
| `c.runner_repos_jour`  | `dict[str, int]`              | Repos jour en segments (résolu)                  |
| `c.runner_repos_nuit`  | `dict[str, int]`              | Repos nuit en segments (résolu)                  |
| `c.night_segments`     | `set[int]`                    | Ensemble des segments de nuit                    |
| `c.segment_km`         | `float`                       | Longueur d'un segment en km                      |
| `c.segment_duration`   | `float`                       | Durée d'un segment en heures                     |
| `c.paired_relays`      | `list[tuple[str,int,str,int]]`| Tous les pairings `(r1,k1,r2,k2)` déclarés      |
| `c.solo_max_size`      | `int`                         | Taille max d'un solo en segments                 |

### Conversions supplémentaires

```python
c.km_to_seg(km) -> int
```
Convertit une distance en km en numéro de segment (arrondi au bas).

```python
c.size_of(relay_name) -> int
```
Retourne la taille en segments du type de relais (lève `ValueError` si le type est flexible).

### Vérification et diagnostic

```python
c.print_summary()          # Affiche le résumé complet (coureurs, compat, relais épinglés, borne LP)
c.compute_upper_bound()    # Calcule le majorant LP (résultat mémorisé dans lp_upper_bound, etc.)
```

La borne LP est calculée automatiquement lors du premier appel à `print_summary()`. Les résultats sont stockés dans :
- `c.lp_upper_bound` (`int`) : borne supérieure arrondie
- `c.lp_upper_bound_exact` (`float`) : valeur LP exacte
- `c.lp_solo_nb` (`float`) : nombre de solos estimé par la relaxation LP
- `c.lp_solo_km` (`float`) : km en solo estimés par la relaxation LP

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

### `Coureur`

Contraintes résumées d'un coureur :

```python
@dataclass
class Coureur:
    relais: list[RelaySpec]
    repos_jour: int | None           # en segments ; None = utilise le défaut global
    repos_nuit: int | None
    solo_max: int | None
    nuit_max: int | None
    max_same_partenaire: int | None  # None = utilise max_same_partenaire global
```

---

## Exemple complet minimal

```python
from constraints import RelayConstraints, RelayIntervals, R20, R15, R15_F, R30
from compat import COMPAT_MATRIX

c = RelayConstraints(
    total_km=440, nb_segments=290, speed_kmh=9.0, start_hour=15.0,
    compat_matrix=COMPAT_MATRIX,
    solo_max_km=17, solo_max_default=1, nuit_max_default=1,
    repos_jour_heures=7, repos_nuit_heures=9,
    enable_flex=True,
)

# Plages temporelles
j1   = RelayIntervals([(0, c.hour_to_seg(15.0, jour=1))])
nuit = c.night_windows()

# Relais partagé (binôme obligatoire)
relay_nuit = c.new_relay(R30)

# Coureurs
alice = c.new_runner("Alice").set_options(nuit_max=2)
alice.add_relay(R20, nb=2).add_relay(R15_F, window=j1)

bob = c.new_runner("Bob").set_options(solo_max=0)
bob.add_relay(relay_nuit, window=nuit).add_relay(R15, nb=3)

carol = c.new_runner("Carol")
carol.add_relay(relay_nuit, window=nuit).add_relay(R15, pinned=0)

def build_constraints():
    return c
```
