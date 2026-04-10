# Package `relay` — référence des modules

Ce document décrit le rôle de chaque module du package `relay` et l'API publique exportée par `relay/__init__.py`. Il s'adresse aux développeurs qui souhaitent comprendre l'architecture interne, étendre le solveur, ou simplement retrouver leurs repères après une longue pause.

Pour l'utilisation courante (ligne de commande, API haut niveau), voir [USAGE.md](USAGE.md).

---

## API publique (`relay/__init__.py`)

Tout ce qui est nécessaire en usage courant s'importe directement depuis `relay` :

```python
from relay import (
    Constraints,         # déclaration du problème
    model,               # factory modèle CP-SAT
    Solver,              # solveur streaming
    Solution,            # solution vérifiée + exports
    diag_faisabilite,    # diagnostic d'infaisabilité
    solution_to_gpx,     # export GPX
    solution_to_kml,     # export KML
    solve,               # résoudre et sauvegarder
    replanif,            # replanifier vers une référence
    optimise_dplus,      # maximiser D+/D- pondéré
    optimise_flex,       # minimiser les écarts taille / cible
    entry_point,         # dispatch CLI
)
```

### Fonctions de haut niveau

| Fonction | Signature | Description |
|---|---|---|
| `solve` | `solve(c, *, min_score, hint, timeout_sec)` | Construit le modèle, fixe l'objectif binômes, charge un hint optionnel, lance le solveur et sauvegarde chaque solution dans `plannings/`. |
| `replanif` | `replanif(c, *, reference, min_score, timeout_sec)` | Charge une solution de référence JSON, minimise les écarts de départs (en km), sauvegarde. `min_score` ajoute une contrainte de score minimal. |
| `optimise_dplus` | `optimise_dplus(c, *, min_score, hint, timeout_sec)` | Maximise `sum(lvl[r] * (D+ + D-))` sous contrainte de score minimal. Requiert `profil_csv=` dans `Constraints`. |
| `optimise_flex` | `optimise_flex(c, *, min_score, timeout_sec)` | Minimise `sum(\|dist − target\|)` (déviation taille cible). À utiliser après `solve()` pour affiner les longueurs tout en conservant le score. |
| `entry_point` | `entry_point(c)` | Dispatch CLI via argparse. Action positionnelle + `--min-score`, `--ref`. Point d'entrée unique pour `example.py`. |

### `entry_point` — actions disponibles

```
data      Afficher le résumé des données et des waypoints
solve     Résoudre (défaut si action absente)
dplus     Maximiser le dénivelé pondéré D+/D-
replanif  Replanifier par rapport à --ref (obligatoire)
diag      Analyser la faisabilité
```

`--ref <fichier.json>` : hint pour `solve`/`dplus`, référence obligatoire pour `replanif`.

---

## Modules

### `relay/constraints.py` — Déclaration du problème

Point d'entrée de toute déclaration. `Constraints` accumule les paramètres globaux de la course et les données des coureurs avant construction du modèle CP-SAT. Traduit les déclarations haut niveau (coureurs, relais, pauses, disponibilités) en structures internes consommées par `model.py`.

Les unités internes sont des **mètres** (distances) et des **minutes** (temps). Les tables `cumul_m` et `cumul_temps` sont précalculées à la construction ; les conversions km/heure → index waypoint utilisent ces tables.

`add_pause()` doit être appelé **avant** toutes les factories `interval_*()` et `new_runner()`.

**Types et classes exposés :**

| Nom | Rôle |
|---|---|
| `Constraints` | Classe principale. Accepte les paramètres globaux et expose `new_runner()`, `new_shared_relay()`, `add_pause()`, `add_max_duos()`, et les factories d'intervalles. |
| `Preset` | NamedTuple `(km, min, max)` — gabarit de taille de relais. Chaque `example.py` déclare les siens. |
| `Interval` | Dataclass `(lo, hi)` — plage d'indices de waypoints. Ne pas instancier directement : utiliser les factories `interval_km/time/waypoints()`. |
| `RunnerBuilder` | Constructeur fluent retourné par `new_runner()`. Chaîne `set_options()` et `add_relay()`. |
| `SharedLeg` | Relais partagé (binôme forcé) : créé par `new_shared_relay()`, passé à `add_relay()` de deux coureurs. |
| `RelaySpec` | Dataclass interne : `target_m`, `min_m`, `max_m`, `paired_with`, `window`, `pinned_start`, `pinned_end`, `dplus_max`. Supporte `to_dict()` / `from_dict()`. |
| `RunnerOptions` | Dataclass interne : `solo_max`, `nuit_max`, `repos_jour_min`, `repos_nuit_min`, `max_same_partenaire`, `lvl`. Supporte `to_dict()` / `from_dict()`. |

**Propriétés dérivées clés :**

| Propriété | Type | Description |
|---|---|---|
| `upper_bound` | `UpperBound \| None` | Majorant heuristique du score (taille=target) — chargé lazy via CP-SAT agrégé |
| `upper_bound_max` | `UpperBound \| None` | Majorant garanti du score (taille=max_m) — chargé lazy |
| `cumul_dplus` | `tuple[list[int], list[int]] \| None` | Tables `(cumul_dp, cumul_dm)` en mètres — chargées lazy depuis `profil_csv` |
| `profil` | `Profile \| None` | Profil altimétrique chargé lazy depuis `profil_csv` |
| `pause_arcs` | `set[int]` | Indices des arcs de pause (exclus de la couverture) |

**Sérialisation :** `to_dict()` / `to_json()` / `from_dict()` / `from_json()`. Les waypoints sont sérialisés sans les points fictifs de pause ; `from_dict()` rejoue `add_pause()` depuis le champ `pauses` pour éviter la double-insertion.

---

### `relay/model.py` — Construction du modèle CP-SAT

Traduit un objet `Constraints` en modèle CP-SAT complet. Crée les variables par relais `(r, k)` — `start`, `end`, `nb_arcs_var`, intervalles CP-SAT — et les familles de contraintes. Chaque famille est isolée dans une méthode dédiée, ce qui permet à `feasibility.py` de construire des modèles partiels.

**Variables principales :**

| Variable | Description |
|---|---|
| `start[r][k]`, `end[r][k]` | Indices de waypoints de début/fin |
| `dist[r][k]`, `time_start[r][k]`, `time_end[r][k]` | Dérivées via `AddElement` sur `cumul_m`/`cumul_temps` |
| `flex[r][k]` | `\|dist − target_m\|` — déviation par rapport à la cible |
| `same_relay[(r,k,rp,kp)]` | BoolVar : vaut 1 iff même `start` ET même `end` |
| `relais_nuit[(r,k)]`, `relais_solo[(r,k)]` | BoolVars de type |
| `dp_s`, `dp_e`, `dm_s`, `dm_e` | Variables D+/D− par relais (créées lazy par `_ensure_dplus_vars`) |

**API publique de `Model` :**

| Méthode | Description |
|---|---|
| `build(c)` | Construit toutes les variables et contraintes. |
| `add_optimisation_func(c)` | Objectif : maximise `BINOME_WEIGHT × score_binômes`. |
| `add_min_score(c, score)` | Contrainte `score_binômes >= score`. |
| `add_optimise_flex()` | Objectif : minimise `sum(flex)`. |
| `add_optimise_dplus(c)` | Objectif : maximise `sum(lvl[r] * (D+ + D-))`. |
| `add_minimise_differences_with(ref_sol, c)` | Objectif : minimise `sum(\|start[r][k] − ref_start\|)` en km. |
| `add_hint_from_solution(sol)` | Charge une solution comme hint CP-SAT (warm-start). |

**Factory :**

`build_model(c, *, min_score)` — construit et retourne un `Model` complet. Exporté sous l'alias `model` dans `__init__.py`.

---

### `relay/solver.py` — Solveur streaming

`Solver` encapsule le solveur CP-SAT d'OR-Tools et expose ses résultats comme un itérateur Python. Le solveur tourne dans un thread séparé ; chaque solution trouvée est transmise via une queue au thread principal.

**API :**

| Élément | Description |
|---|---|
| `Solver(model, constraints)` | Initialisation. |
| `solve(timeout_sec, max_count, log_progress)` | Générateur qui yield des `Solution`. S'arrête au timeout ou au nombre max de solutions. |
| `SOLVER_NUM_WORKERS` | Constante (10) — nombre de workers CP-SAT en parallèle. |
| `SOLVER_TIME_LIMIT` | Constante (0 = illimité). |

---

### `relay/solution.py` — Solution vérifiée et exports

`Solution` encapsule une liste de relais attribués (chacun sous forme de `dict`) avec toutes les métadonnées calculées lors de l'extraction. Le constructeur déclenche automatiquement `verifications.check()` et stocke le résultat dans `.valid`.

**Champs de chaque relais :**
`runner`, `k`, `start`, `end`, `wp_start`, `wp_end`, `km_start`, `km_end`, `lat/lon/alt_start/end`, `km`, `target_km`, `time_start_min`, `time_end_min`, `solo`, `night`, `partner`, `pinned`, `rest_min_h`, `rest_h`, `d_plus`, `d_moins`.

**API :**

| Méthode / classmethod | Description |
|---|---|
| `from_cpsat(callback)` | Extrait une solution depuis le callback CP-SAT. Calcule D+/D− via `constraints.profil`. |
| `from_dict(data)` / `from_json(path)` | Charge une solution sérialisée. Appelle `check()` automatiquement. |
| `to_text()` | Planning complet en texte (chronologique + récapitulatif par coureur). |
| `to_csv(filename)` | Export CSV tabulaire. |
| `to_json(filename)` | Export JSON (format rechargeable). |
| `to_html(filename)` | Export HTML avec Gantt SVG sur axe temporel. |
| `save(*, as_json, csv, html, txt, gpx)` | Sauvegarde les formats demandés (tous True par défaut) dans `plannings/` avec horodatage. GPX/KML si `parcours_gpx=` est défini. |
| `stats()` | Retourne un `SolutionStats` dataclass. |
| `print_summary(suffix)` | Affiche un résumé compact sur stdout avec score duos, solos, flex ±, score D+. |

**`SolutionStats` dataclass :**

| Champ | Description |
|---|---|
| `score_duos` | Somme des scores de compatibilité des binômes |
| `nb_duos`, `nb_solo`, `km_solo` | Décomptes et distance des solos |
| `nb_pinned` | Nombre de relais épinglés |
| `flex_plus`, `flex_moins` | Allongements / raccourcissements totaux en km |
| `score_dplus` | `sum(lvl[r] * (D+ + D-))` par coureur |
| `ub_score_target` | Majorant heuristique du score (taille=target) — `None` si non calculé |
| `ub_score_max` | Majorant garanti du score (taille=max_m) — `None` si non calculé |
| `lb_solos` | Borne basse sur le nombre de solos — `None` si non calculé |

---

### `relay/feasibility.py` — Diagnostic d'infaisabilité

Quand le solveur ne trouve pas de solution, ce module aide à identifier quelle(s) contrainte(s) causent l'infaisabilité. Il procède en trois phases : test du modèle complet, désactivation famille par famille, puis forage fin par coureur ou par relais.

**API :**

| Élément | Description |
|---|---|
| `FeasibilityAnalyser(constraints, timeout=10.0)` | Classe principale. |
| `FeasibilityAnalyser.run()` | Lance l'analyse en trois phases et affiche le rapport. |
| `diag_faisabilite(constraints, timeout=10.0)` | Fonction raccourci. Exportée dans `relay.__all__`. |

**Familles de contraintes testables :** `symmetry_breaking`, `fixed_relays`, `pause_constraints`, `coverage`, `same_relay`, `inter_runner_no_overlap`, `night_relay`, `solo`, `rest_intervals`, `availability`, `shared_relays`, `max_duos`, `max_same_partenaire`, `dplus_max`.

---

### `relay/verifications.py` — Vérifications post-résolution

Double vérification indépendante du modèle CP-SAT. Détecte les incohérences de modélisation. Appelé automatiquement par `Solution.from_cpsat()` et `Solution.from_dict()`.

**API :**

| Fonction | Description |
|---|---|
| `check(solution, out=stdout)` | Vérifie la solution. Retourne `bool`. Affiche les erreurs sur `out`. |

**Vérifications couvertes :** couverture complète (1–2× par arc non-pause), pauses (aucun relais ne traverse un arc de pause), tailles relais (min/max respectés), repos jour/nuit, limites nocturnes, solos (distance cap + zone interdite par chevauchement), no-overlap entre coureurs, pairings `SharedLeg`, compatibilité des partenaires, `add_max_duos`.

---

### `relay/formatters.py` — Rendu texte, CSV, HTML

Fonctions de rendu appelées par `Solution`.

| Fonction | Description |
|---|---|
| `to_text(solution)` | Planning complet en texte |
| `to_csv(solution, filename)` | Export CSV tabulaire |
| `to_html(solution)` | Export HTML (appelle `build_gantt`) |

`TRI_GANTT` : constante contrôlant l'ordre des lignes du Gantt (`"decl"` par défaut, `"alpha"`, `"start"`).

---

### `relay/gantt.py` — Gantt SVG sur axe temporel

Génère le bloc Gantt SVG intégré dans l'export HTML.

| Élément | Description |
|---|---|
| `build_gantt(solution)` | Retourne un `div.gantt-grid` HTML complet |
| `GANTT_CSS` | Bloc `<style>` à inclure dans le HTML |
| `ROW_HEIGHT`, `OVERLAY_HEIGHT`, `TICK_STEP_H` | Constantes de dimensionnement |
| `TRI_GANTT` | Ordre des lignes : `"decl"`, `"alpha"` ou `"start"` |

Les bandes de nuit et les arcs de pause sont rendus en overlays sur l'axe temporel.

---

### `relay/gpx.py` — Export GPX et KML

| Fonction | Description |
|---|---|
| `solution_to_gpx(solution, gpx_source, output_path)` | Un `<trk>` par relais + `<wpt>` par borne ; coordonnées GPS depuis `constraints.waypoints` |
| `solution_to_kml(solution, gpx_source, output_path)` | Un `<Folder>` par coureur, lignes colorées + points de passage |

Appelées automatiquement par `save()` si `parcours_gpx=` est défini dans `Constraints`.

---

### `relay/upper_bound.py` — Borne supérieure du score

Résout un modèle CP-SAT agrégé (sans contraintes positionnelles) pour calculer deux majorants du score de compatibilité.

| Élément | Description |
|---|---|
| `UpperBound` | NamedTuple : `score`, `score_exact`, `n_binomes`, `n_solos` |
| `compute_upper_bounds(c, timeout_sec=3.0)` | Retourne `(ub_target, ub_max)` |

- `ub_target` : majorant heuristique avec `size=target_m` (serré, non garanti)
- `ub_max` : majorant garanti avec `size=max_m` (toujours ≥ vrai optimum)

Accessibles via les propriétés lazy `constraints.upper_bound` et `constraints.upper_bound_max`. Propagés dans `SolutionStats.ub_score_target`, `ub_score_max`, `lb_solos`.

---

### `relay/profil.py` — Profil altimétrique

Charge le profil d'altitude depuis un CSV et fournit deux services : calcul du dénivelé D+/D− entre deux km, et rendu SVG du profil.

| Élément | Description |
|---|---|
| `Profile(distances, altitudes)` | Classe principale. |
| `Profile.denivele(km_deb, km_fin)` | Retourne `(d_plus, d_moins)` en mètres. |
| `Profile.to_svg(...)` | Génère un SVG du profil avec axe temporel optionnel et bandes de pause. |
| `load_profile(filename)` | Charge depuis `gpx/altitude.csv` et retourne un `Profile`. |

Chargé lazy via `constraints.profil`. Requis pour `dplus_max` et `optimise_dplus`.
