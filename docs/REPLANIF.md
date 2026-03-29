# Replanification

La replanification produit un nouveau planning à partir d'une **solution de référence** existante, après que les données du problème ont changé. L'objectif du solveur est modifié : au lieu de maximiser le score de compatibilité des binômes, il **minimise les écarts par rapport à la référence** tout en respectant les nouvelles contraintes.

## Cas d'usage typiques

- Un coureur se blesse ou devient indisponible → modifier ses contraintes ou supprimer ses relais
- Des relais déjà courus doivent être épinglés (`pinned=`) pour ne plus être déplacés
- Une pause race est décalée → modifier `add_pause()`
- Un coureur change de distance ou de créneau horaire → modifier `add_relay()` / `set_options()`
- Un relais est ajouté ou supprimé → ajouter/retirer un `add_relay()`

## Principe de la métrique de distance

La distance entre le nouveau planning et la référence est définie comme :

```
distance = Σ |start[coureur][k] - ref_start[coureur][k]|
```

Pour chaque relais `(coureur, k)` présent dans les deux solutions, on mesure le déplacement du segment de départ en unités de segments. Le solveur minimise cette somme totale.

**L'indice `k`** est l'index du relais dans la liste déclarée pour un coureur (visible dans les exports CSV et JSON sous la colonne `k`). Il est attribué dans l'ordre de déclaration dans `example.py`. Si vous réordonnez les `add_relay()` d'un coureur entre deux runs, les indices `k` changent, et la distance calculée peut être très élevée même si les relais sont proches — **le solveur associe référence et nouveau relais par indice `k`, pas par position géographique**.

**Recommandation** : conserver l'ordre de déclaration des relais d'un coureur entre la solution de référence et la replanification. Si vous ajoutez un relais, ajoutez-le en fin de liste pour ne pas décaler les indices existants. Si vous en supprimez un, prenez en compte que les indices suivants seront décalés.

## Comparaison solve vs replanif

| Aspect | `solve` (optimisation standard) | `replanif` (replanification) |
|---|---|---|
| **Fonction objectif** | Maximise `BINOME_WEIGHT × score_binômes − pénalité_flex` | Minimise `Σ \|start[k] − ref_start[k]\|` |
| **Contrainte score minimal** | Non (objectif déjà orienté score) | Optionnelle via `add_min_score` / `--min-score` |
| **API ligne de commande** | `python example.py` | `python example.py --replanif ref.json [--min-score 88]` |
| **API scriptable** | `relay.solve(c)` | `relay.replanif(c, reference="ref.json", min_score=88)` |
| **Sortie** | Fichiers horodatés dans `plannings/` | Fichiers horodatés dans `plannings/` |

## API ligne de commande

```bash
# Replanification simple (minimise les écarts)
python example.py --replanif plannings/solution_reference.json

# Avec contrainte de score minimal
python example.py --replanif plannings/solution_reference.json --min-score 88
```

## API scriptable

```python
import relay
from relay import Constraints, Intervals, R15, R20

c = Constraints(
    total_km=440, nb_segments=176, speed_kmh=9.0, start_hour=15.0,
    compat_matrix=COMPAT_MATRIX, ...
)
# ... déclarer les coureurs avec les nouvelles contraintes ...

# Replanification minimisant les écarts avec la référence
relay.replanif(c, reference="replanif/reference.json")

# Avec score minimal garanti
relay.replanif(c, reference="replanif/reference.json", min_score=88)

# Avec timeout
relay.replanif(c, reference="replanif/reference.json", timeout_sec=120)
```

Pour construire le modèle manuellement (accès complet) :

```python
from relay import Solution, model as build_model, Solver

ref = Solution.from_json("plannings/solution_reference.json")
m = build_model(c)
m.add_minimise_differences_with(ref)
m.add_min_score(c, 88)          # optionnel

solver = Solver(m, c)
for sol in solver.solve(timeout_sec=120):
    sol.save()
```

## Exemples concrets

### 1. Coureur blessé — retrait de ses relais

Un coureur prévu avec 3 relais R15 est indisponible. On supprime simplement ses `add_relay()` et on retire son entrée du planning. Le solveur redistribue la couverture en minimisant les déplacements des autres coureurs.

```python
# Avant (solution de référence)
marc = c.new_runner("Marc")
marc.add_relay(R15, nb=3)

# Après (replanification)
# Marc est retiré — ne pas déclarer new_runner("Marc")
# Les autres coureurs absorbent ses segments
relay.replanif(c, reference="plannings/ref_avec_marc.json")
```

### 2. Épinglage des relais déjà courus

À mi-course, les relais courus sont fixés (`pinned=`) pour qu'ils ne soient plus déplacés. Seuls les relais restants sont optimisés.

```python
# seg 42 est le dernier segment couru par Alice
alice = c.new_runner("Alice")
alice.add_relay(R15, nb=1, pinned=c.km_to_seg(10))   # relais 1 : déjà couru, épinglé
alice.add_relay(R15, nb=1, pinned=c.km_to_seg(22))   # relais 2 : déjà couru, épinglé
alice.add_relay(R20, nb=1)                            # relais 3 : à planifier

relay.replanif(c, reference="plannings/ref_depart.json")
```

### 3. Pause décalée

La pause initialement prévue au segment 60 est avancée au segment 55 (incident de course). Les relais autour de la pause sont réorganisés au plus près de la référence.

```python
# Avant : c.add_pause(60, duree=1.5)
# Après :
c.add_pause(55, duree=1.5)

relay.replanif(c, reference="plannings/ref_pause_60.json")
```

### 4. Replanification avec garantie de qualité

On souhaite rester proche de la référence tout en garantissant un score de compatibilité d'au moins 85 (éviter de casser des binômes clés).

```bash
python example.py --replanif plannings/ref.json --min-score 85
```

```python
relay.replanif(c, reference="plannings/ref.json", min_score=85)
```

Si le score minimal est infaisable avec la contrainte de proximité, le solveur sera insatisfaisable — dans ce cas, baisser `min_score` ou relancer sans cette contrainte.
