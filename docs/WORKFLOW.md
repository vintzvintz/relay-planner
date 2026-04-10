# Workflow typique

Ce document décrit le processus recommandé pour planifier un relais, de la première résolution jusqu'à la replanification en cours de course.

---

## Étape 1 — Déclarer les données d'entrée

Créer un script Python (ex. `example.py`) avec les données de course, les coureurs et leurs relais, puis appeler `relay.entry_point(c)` en fin de script.

```python
import relay
from relay import Constraints
from relay.constraints import Preset

R15 = Preset(km=15, min=13, max=17)
R20 = Preset(km=20, min=18, max=22)

c = Constraints(
    parcours_gpx="gpx/parcours.gpx",  # waypoints + profil altimétrique + active GPX/KML export
    speed_kmh=9.0,
    start_hour=14.0,
    compat_matrix="compat_coureurs.xlsx",  # chemin xlsx ou dict[tuple[str,str], int]
    solo_max_default=1,
)

alice = c.new_runner("Alice", lvl=4)
alice.add_relay(R15).add_relay(R15).add_relay(R15)

bob = c.new_runner("Bob", lvl=2)
bob.add_relay(R20).add_relay(R20)

# ...

relay.entry_point(c)
```

```bash
python example.py data   # résumé des données
python example.py diag   # analyse de faisabilité
```

---

## Étape 2 — Consulter les bornes théoriques

Avant de lancer le solveur complet, consulter les bornes supérieures calculées sans les contraintes structurantes (disponibilité, repos, compatibilité). Ces bornes indiquent le score maximum atteignable en théorie.

```bash
python example.py data
```

La sortie affiche `ub_score_target` et `ub_score_max` (bornes supérieures du score duo) et `lb_solos` (borne inférieure du nombre de solos).

Exemple : `score_duo ≤ 48`, `solo_min ≥ 7`

Ces bornes servent de référence pour les étapes suivantes : inutile de continuer à chercher au-delà.

---

## Étape 3 — Optimiser le score duo

Lancer le solveur en mode `solve` (objectif : maximiser le score des binômes).

```bash
python example.py solve
# ou avec un score minimal garanti :
python example.py solve --min-score 46
```

**Critère d'arrêt** : s'approcher des bornes théoriques (ex. atteindre 46–47 si la borne est 48), ou après 30 à 60 minutes.

Le score duo optimise implicitement les solos et la compacité des relais, car :
- Un relais solo contribue 0 au score.
- Un relais flex réduit (ex. 15 km raccourci à 10 km) augmente la distance minimale à couvrir en solo → diminue le score.

---

## Étape 4 — Conserver la solution de référence

Copier la meilleure solution pour l'utiliser comme point de départ des étapes suivantes.

**Option rapide** — copie automatique vers `replanif/reference.*` :

```bash
python utils/update_reference.py
```

Détecte le sous-répertoire le plus récent dans `plannings/` et copie tous les formats (`.json`, `.csv`, `.html`, `.txt`, `.gpx`, `.kml`) vers `replanif/reference.*`.

**Option manuelle** — copie vers un dossier `refs/` personnalisé :

```bash
mkdir -p refs
cp plannings/<YYYYMMDD_HHMMSS>_solve/planning.json refs/solution_duos.json
```

---

## Étape 5 — Optimiser la répartition du dénivelé

Lancer le solveur en mode `dplus` (objectif : maximiser le dénivelé affecté aux coureurs pondéré par leur `lvl`), en ajoutant une contrainte de score minimal pour conserver des solutions de bonne qualité.

```bash
python example.py dplus --ref refs/solution_duos.json --min-score 46
```

- `--ref` charge la solution de l'étape 3 comme **hint** pour accélérer la recherche de solutions au voisinage de l'étape 4.
Sans cela l'optimisation D+ est plus lente que la résolution normale.
- `--min-score` = 1 à 3 points en dessous du score de la solution de référence pour élargir l'espace de solutions sans trop dégrader la qualité.

**Compromis attendu** : 1 ou 2 binômes sous-optimaux, voire 1 solo supplémentaire, en échange d'une meilleure affectation des segments difficiles aux coureurs qui les apprécient.

**Surveiller** le score duo et le nombre de solos dans la sortie :

> Attention : 2 duos « moyens » (score 1 × 2) ont la même valeur qu'1 « bon » duo (score 2 × 1) + 2 solos (score 0).
> Pour changer cet équilibre, modifier la matrice de compatibilité (ex. utiliser des valeurs 33/66 au lieu de 50/50).

---

## Étape 6 — Conserver la solution finale

Sauvegarder la solution D+ comme base pour les itérations et replanifications futures.

```bash
cp plannings/<YYYYMMDD_HHMMSS>_dplus/planning.json refs/solution_finale.json
```

---

## Étape 7 — Replanification

La replanification produit un nouveau planning à partir d'une **solution de référence** existante, après que les données du problème ont changé. L'objectif du solveur est modifié : au lieu de maximiser le score de compatibilité des binômes, il **minimise les écarts par rapport à la référence** tout en respectant les nouvelles contraintes.

### Cas d'usage typiques

- Un coureur se blesse ou devient indisponible → modifier ses contraintes ou supprimer ses relais
- Des relais déjà courus doivent être épinglés pour ne plus être déplacés
- Une pause race est décalée → modifier `add_pause()`
- Un coureur change de distance ou de créneau horaire → modifier `add_relay()` / `set_options()`
- Un relais est ajouté ou supprimé → ajouter/retirer un `add_relay()`
- Forcer les relais à certains endroits précis → ajouter une pause de durée nulle au point souhaité

### Procédure

1. Copier le script d'origine dans un nouveau fichier (ex. `replanif.py`)
2. Appliquer les modifications souhaitées (coureurs, relais, contraintes, épinglages)
3. Relancer le solveur en mode `replanif` :

```bash
python replanif.py replanif --ref refs/solution_finale.json
# Avec contrainte de score minimal :
python replanif.py replanif --ref refs/solution_finale.json --min-score 44
```

### Principe de la métrique de distance

La distance entre le nouveau planning et la référence est définie comme :

```
distance = Σ |start[coureur][k] - ref_start[coureur][k]|
```

Pour chaque relais `(coureur, k)`, on mesure le déplacement du point de départ. Le solveur minimise cette somme totale.

**L'indice `k`** est l'index du relais dans la liste déclarée pour un coureur (visible dans les exports CSV et JSON). Il est attribué dans l'ordre de déclaration dans le script. Si vous réordonnez les `add_relay()` d'un coureur entre deux runs, les indices `k` changent.

**Recommandation** : conserver l'ordre de déclaration des relais entre la référence et la replanification. Si vous ajoutez un relais, ajoutez-le en fin de liste. Si vous en supprimez un, prenez en compte le décalage des indices suivants.

### Comparaison solve vs replanif

| Aspect | `solve` | `replanif` |
|---|---|---|
| **Fonction objectif** | Maximise le score des binômes | Minimise `Σ \|start[k] − ref_start[k]\|` |
| **Contrainte score minimal** | Optionnelle via `--min-score` | Optionnelle via `--min-score` |
| **CLI** | `python example.py solve` | `python example.py replanif --ref ref.json` |
| **API** | `relay.solve(c)` | `relay.replanif(c, reference="ref.json")` |

### Exemples concrets

#### Coureur blessé — retrait de ses relais

```python
# Avant (solution de référence) : marc avait 3 relais
# Après : supprimer les lignes new_runner("Marc") et add_relay()
# Les autres coureurs absorbent ses segments
relay.replanif(c, reference="refs/solution_avec_marc.json")
```

#### Épinglage des relais déjà courus

```python
alice = c.new_runner("Alice", lvl=4)
alice.add_relay(R15, start_km=10, end_km=25)   # relais 1 : épinglé (déjà couru)
alice.add_relay(R15, start_km=38, end_km=52)   # relais 2 : épinglé (déjà couru)
alice.add_relay(R20)                            # relais 3 : à planifier

relay.replanif(c, reference="refs/solution_depart.json")
```

#### Pause décalée

```python
# Avant : c.add_pause(duree_heures=1.5, km=60)
# Après :
c.add_pause(duree_heures=1.5, km=55)

relay.replanif(c, reference="refs/solution_pause_60.json")
```

#### Replanification avec garantie de qualité

```bash
python example.py replanif --ref refs/solution_finale.json --min-score 44
```

Si le score minimal est infaisable avec la contrainte de proximité, le solveur sera insatisfaisable — dans ce cas, baisser `--min-score` ou relancer sans cette contrainte.

---

## Résumé des commandes CLI

```bash
python example.py              # solve (défaut)
python example.py data         # résumé des données et bornes
python example.py diag         # analyse de faisabilité
python example.py solve        # optimise score duo
python example.py solve --min-score 46
python example.py dplus --ref refs/solution.json --min-score 46
python example.py replanif --ref refs/solution.json
python example.py replanif --ref refs/solution.json --min-score 44
```
