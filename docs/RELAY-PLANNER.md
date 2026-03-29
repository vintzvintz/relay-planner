# Package `relay` — référence des modules

Ce document décrit le rôle de chaque module du package `relay` et l'API publique exportée par `relay/__init__.py`. Il s'adresse aux développeurs qui souhaitent comprendre l'architecture interne, étendre le solveur, ou simplement retrouver leurs repères après une longue pause.

Pour l'utilisation courante (ligne de commande, API haut niveau), voir [USAGE.md](USAGE.md).

---

## API publique (`relay/__init__.py`)

Tout ce qui est nécessaire en usage courant s'importe directement depuis `relay` :

```python
from relay import (
    Constraints, Intervals, SharedLeg,   # déclaration du problème
    R10, R15, R20, R30, R13_F, R15_F,   # constantes de types de relais
    model,                                # factory modèle CP-SAT
    Solver,                               # solveur streaming
    Solution,                             # solution vérifiée + exports
    solve, replanif, entry_point,        # fonctions de haut niveau
)
# Disponibles mais non réexportés dans __all__ :
from relay import diagnose               # alias de feasibility.analyse
from relay.constraints import RunnerBuilder
from relay.model import Model
from relay.feasibility import FeasibilityAnalyser
```

### Fonctions de haut niveau

| Fonction | Description |
|---|---|
| `solve(c, *, timeout_sec=0)` | Construit le modèle, fixe l'objectif, lance le solveur et sauvegarde chaque solution trouvée dans `plannings/`. |
| `replanif(c, *, reference, min_score=None, timeout_sec=0)` | Charge une solution de référence JSON, minimise les écarts avec elle, et sauvegarde les nouvelles solutions. `min_score` ajoute optionnellement une contrainte de score minimal. |
| `entry_point(c)` | Dispatch CLI : parse `sys.argv` et appelle `--summary`, `--diag`, `--model`, `--replanif`, ou `solve()` par défaut. Point d'entrée unique pour `example.py`. |
| `diagnose(c)` | Raccourci pour `FeasibilityAnalyser(c).run()` — analyse systématique de l'infaisabilité. Importable depuis `relay` mais absent de `__all__`. |
| `model(c)` | Factory : construit et retourne un `Model` prêt à l'emploi (alias de `build_model`). |

### Constantes de types de relais

`R10`, `R15`, `R20`, `R30` — relais à taille fixe (10, 15, 20, 30 km).
`R13_F`, `R15_F` — relais flexibles (la taille peut être réduite si le coureur forme un binôme avec un partenaire ayant un relais plus court).

---

## Modules

### `relay/constraints.py` — Déclaration du problème

C'est le point d'entrée de toute déclaration. La classe `Constraints` accumule tous les paramètres de la course et les données des coureurs avant que le modèle CP-SAT ne soit construit. Elle traduit les déclarations haut niveau (coureurs, relais, pauses, disponibilités) en structures internes consommées par `model.py`.

`Constraints` calcule également les propriétés dérivées : liste des segments actifs et inactifs, segments nocturnes, borne supérieure LP (relaxation linéaire via GLOP), et conversions heures ↔ segments ↔ km. La propriété `profil` charge lazily le profil altimétrique depuis le CSV si `profil_csv` est fourni.

**Types et classes exposés :**

| Nom | Rôle |
|---|---|
| `Constraints` | Classe principale. Accepte les paramètres globaux de la course et expose `new_runner()`, `new_relay()`, `add_pause()`, `add_max_binomes()`. |
| `RunnerBuilder` | Constructeur fluent retourné par `new_runner()`. Chaîne `set_options()` et `add_relay()`. Non réexporté dans `relay.__all__` — importer depuis `relay.constraints` si nécessaire. |
| `SharedLeg` | Relais partagé (binôme forcé) : créé par `new_relay()`, passé à `add_relay()` de deux coureurs. |
| `Intervals` | Fenêtre de disponibilité ou de placement : `Intervals([(start, end), ...])` en indices de segments actifs. |
| `RelaySpec` | Dataclass interne : `size` (ensemble de tailles), `paired_with`, `window`, `pinned`. |
| `Coureur` | Dataclass interne agrégeant les options d'un coureur après `set_options()`. |
| `R10`, `R15`, `R20`, `R30`, `R13_F`, `R15_F` | Constantes chaîne des types de relais, passées à `add_relay(size=...)`. |
| `make_relay_types()` | Calcule les ensembles de tailles (en segments) pour chaque type de relais. Appelé en interne par `Constraints.__init__`. |

---

### `relay/model.py` — Construction du modèle CP-SAT

Ce module traduit un objet `Constraints` en un modèle CP-SAT complet. Il crée toutes les variables (`start`, `end`, `size`, `same_relay`, `relais_solo`, `relais_nuit`…) et ajoute les familles de contraintes une par une. Chaque famille est isolée dans une méthode privée (`_add_coverage`, `_add_rest_constraints`, `_add_availability`, etc.), ce qui facilite le diagnostic dans `feasibility.py` qui peut construire des modèles partiels en omettant certaines familles.

La classe `Model` ne lance pas le solveur — elle ne fait que décrire le problème. La fonction objectif et les contraintes optionnelles (score minimal, minimisation des écarts) sont ajoutées séparément avant de passer le modèle à `Solver`.

**API publique de `Model` :**

| Méthode | Description |
|---|---|
| `build(constraints)` | Construit toutes les variables et contraintes. Appelé par `build_model()`. |
| `add_optimisation_func(c)` | Fixe l'objectif : maximise `BINOME_WEIGHT × score_binômes − pénalité_flex`. |
| `add_min_score(c, score)` | Ajoute une contrainte `score >= score` (compatible avec `add_minimise_differences_with`). |
| `add_minimise_differences_with(solution)` | Remplace l'objectif par la minimisation de `Σ \|start[k] − ref_start[k]\|`. |
| `add_hint(solution)` | Injecte des hints CP-SAT (warm-start) à partir d'une `Solution` existante. |

**Factory :**

| Fonction | Description |
|---|---|
| `build_model(constraints)` | Construit et retourne un `Model` complet. Exporté sous l'alias `model` dans `__init__.py`. La classe `Model` elle-même n'est pas réexportée — importer depuis `relay.model` si nécessaire. |

---

### `relay/solver.py` — Solveur streaming

`Solver` encapsule le solveur CP-SAT d'OR-Tools et expose ses résultats comme un itérateur Python. Le solveur tourne dans un thread séparé ; chaque solution trouvée est transmise via une queue au thread principal. Cela permet de traiter les solutions au fur et à mesure sans attendre la fin de la recherche.

La méthode `solve()` est un générateur : on peut l'interrompre après la première solution ou laisser tourner jusqu'au timeout. Les solutions sont validées par `verifications.check()` avant d'être émises.

**API :**

| Élément | Description |
|---|---|
| `Solver(model, constraints)` | Initialisation. |
| `solve(timeout_sec, target_score, max_count, log_progress)` | Générateur qui yield des `Solution`. S'arrête au premier critère atteint : timeout, score cible, ou nombre max de solutions. |
| `SOLVER_NUM_WORKERS` | Constante (12) — nombre de workers CP-SAT en parallèle. |
| `SOLVER_TIME_LIMIT` | Constante (0 = illimité). |

---

### `relay/solution.py` — Solution vérifiée et exports

`Solution` encapsule une liste de relais attribués (chacun sous forme de `dict`) avec toutes les métadonnées calculées lors de l'extraction (dénivelés, repos, partenaires…). Le constructeur déclenche automatiquement `verifications.check()` et stocke le résultat dans `.valid`.

La classe gère à la fois la création depuis le solveur (`from_cpsat`) et le rechargement depuis un fichier (`from_json`), ce qui permet de post-traiter ou replanifier des solutions sauvegardées.

**API :**

| Méthode / classmethod | Description |
|---|---|
| `from_cpsat(solver)` | Extrait une solution depuis le callback CP-SAT actif. Calcule D+/D− via `constraints.profil` si disponible. |
| `from_json(path, constraints=None)` | Charge une solution JSON. `valid` sera `None` si `constraints` est omis. |
| `to_text()` | Planning complet en texte (chronologique + récapitulatif par coureur). |
| `to_csv(filename)` | Export CSV tabulaire. |
| `to_json(filename)` | Export JSON (format rechargeable). |
| `to_html(filename)` | Export HTML avec Gantt coloré par coureur. |
| `save()` | Sauvegarde les 4 formats horodatés dans `plannings/` et affiche les stats. |
| `stats()` | Retourne `(score, n_binomes, n_solos, km_solos, n_flex, n_pinned, km_flex)`. |

---

### `relay/feasibility.py` — Diagnostic d'infaisabilité

Quand le solveur ne trouve pas de solution, ce module aide à identifier quelle(s) contrainte(s) causent l'infaisabilité. Il procède en trois phases : test du modèle complet, désactivation famille par famille pour isoler les familles suspectes, puis forage fin par coureur ou par relais pour pointer la source exacte.

Le diagnostic est accessible via `python example.py --diag` ou `relay.diagnose(c)`. Il fonctionne avec un timeout court (10 s par test) pour rester rapide même sur des modèles complexes.

**API :**

| Élément | Description |
|---|---|
| `FeasibilityAnalyser(constraints)` | Classe principale. Non réexportée dans `relay.__all__` — importer depuis `relay.feasibility`. |
| `FeasibilityAnalyser.run()` | Lance l'analyse en trois phases et affiche le rapport. |
| `analyse(constraints, timeout=10.0)` | Fonction raccourci. Importable depuis `relay` sous l'alias `diagnose`, absent de `__all__`. |

**Familles de contraintes testables :** couverture, no-overlap, repos, nuit, solo, disponibilités, relais épinglés, binômes forcés, `max_same_partenaire`, `add_max_binomes`.

---

### `relay/verifications.py` — Vérifications post-résolution

Après chaque solution trouvée par le solveur, ce module vérifie que la solution respecte bien toutes les contraintes métier. Il s'agit d'une double vérification indépendante du modèle CP-SAT, utile pour détecter d'éventuelles incohérences de modélisation.

Les vérifications portent sur : couverture complète des segments, tailles de relais, temps de repos jour/nuit, limites nocturnes et solos, fenêtre d'autorisation des solos, absence de chevauchement entre coureurs, binômes forcés, et compatibilité entre partenaires.

**API :**

| Fonction | Description |
|---|---|
| `check(solution, constraints)` | Vérifie la solution. Retourne `True` si tout est valide. Les erreurs sont loggées sur stderr. |

---

### `relay/profil.py` — Profil altimétrique

Ce module charge le profil altimétrique du parcours depuis un CSV et fournit deux services : le calcul du dénivelé positif/négatif entre deux points kilométriques (utilisé lors de l'extraction des solutions), et le rendu SVG du profil (utilisé dans les exports HTML).

**API :**

| Élément | Description |
|---|---|
| `Profile(distances, altitudes)` | Classe principale. |
| `denivele(km_deb, km_fin)` | Retourne `(d_plus, d_moins)` en mètres entre deux points km. |
| `to_svg(...)` | Génère un SVG du profil avec axe temporel optionnel et bandes de pause. |
| `load_profile(filename=DEFAULT_PROFILE)` | Charge `gpx/altitude.csv` et retourne un `Profile`. |
| `DEFAULT_PROFILE` | Constante : `"gpx/altitude.csv"`. |
