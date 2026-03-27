# relais-planner

Planificateur de course en relais par contraintes (CP-SAT).

Problème : Lyon → Fessenheim, 440 km, ~176 segments (2,5 km/segment), vitesse ~9 km/h, départ mercredi 15h00.
15 coureurs doivent couvrir chaque segment (1 ou 2 coureurs par segment).
L'objectif est de maximiser un score mixte (binômes pondérés par compatibilité + bonus km flex).

## Prérequis

Python 3.10+, puis :

```bash
python -m venv venv
source venv/Scripts/activate
pip install -r requirements.txt
```

## Déclaration des contraintes

Le problème est défini via une API déclarative dans `data.py` :

```python
c = RelayConstraints(total_km=440, nb_segments=176, ...)

pierre = c.new_runner("Pierre")
pierre.add_relay(R20).add_relay(R15_F, nb=3)

nuit1 = c.new_relay(R30)           # relais partagé (binôme forcé)
alexis.add_relay(nuit1, window=nuit1_30k)
olivier.add_relay(nuit1, window=nuit1_30k)
```

Voir [CONSTRAINTS.md](CONSTRAINTS.md) pour la référence complète de l'API.

## Scripts principaux

### `data.py`
Déclare les paramètres globaux du parcours, les coureurs et leurs relais via l'API de `constraints.py`.
Les constantes de types de relais (`R10`, `R15`, `R20`, `R30`, `R13_F`, `R15_F`) sont définies dans `constraints.py` et importées ici.
`build_constraints()` retourne l'objet `RelayConstraints` utilisé par le solveur.
Exécuter directement pour afficher un résumé complet et le majorant LP.

```bash
python data.py
```

### `constraints.py`
Classe `RelayConstraints` : accumule la déclaration des coureurs et relais, calcule les propriétés dérivées (segments nuit, borne supérieure LP, etc.) et expose `print_summary()`.
Définit aussi les constantes de types de relais (`R10`, `R15`, `R20`, `R30`, `R13_F`, `R15_F`) et la fonction `make_relay_types()`.
Types associés : `RunnerBuilder`, `SharedRelay`, `RelaySpec`, `Coureur`, `RelayIntervals`.
Options coureur via `RunnerBuilder.set_options(solo_max, nuit_max, repos_jour, repos_nuit, max_same_partenaire)` ;
`add_max_binomes(runner1, runner2, nb)` pour limiter les binômes entre deux coureurs.
Méthode `add_pause(seg, duree)` : déclare une pause planifiée après le segment actif `seg`, de durée `duree` heures —
insère des segments **inactifs** dans la timeline espace-temps ; le modèle interdit tout relais couvrant ces segments.
`nb_segments` (espace-temps) augmente ; `nb_active_segments` reste fixe. Les contraintes de repos n'ont pas besoin
de crédit de pause : le gap entre deux relais inclut automatiquement les pauses intercalées.
Lève `RuntimeError` si appelée après `new_runner()`.
**API publique unifiée en segments actifs :** `hour_to_seg()`, `km_to_seg()` et `night_windows()` retournent tous des
indices de segments actifs. `add_relay(window=, pinned=)` accepte des indices actifs et fait la conversion
actif→temps en interne. Utiliser `c.last_active_seg` (= `nb_active_segments`) comme borne supérieure
dans `RelayIntervals` (et non `c.nb_segments` qui est un index espace-temps).
La borne LP est mémorisée dans `lp_upper_bound`/`lp_upper_bound_exact`/`lp_solo_nb`/`lp_solo_km` après le premier calcul.
Pas destiné à être exécuté directement.

### `compat.py`
`COMPAT_MATRIX` : scores de compatibilité (0, 1 ou 2) pour chaque paire de coureurs.
Stocke uniquement le triangle inférieur (clé canonique) ; `RelayConstraints` reconstruit la symétrie à la lecture.
Généré automatiquement depuis `compat_coureurs.xlsx` par `refresh_compat.py`.

### `model.py`
Construction du modèle CP-SAT (`RelayModel`). Variables : `start/end/size` par relais,
`same_relay` (binômes), `relais_solo`, `relais_nuit`, `relais_solo_interdit`. Objectif mixte :
somme pondérée des binômes (poids = score de compatibilité) moins une pénalité flex
(relais flex raccourcis en dessous de leur taille nominale).
Brise-symétrie automatique pour les relais identiques non pinnés d'un même coureur.
Pauses encodées comme plages de segments inactifs dans la timeline espace-temps.
Expose `build_model(constraints)`, `add_optimisation_func(constraints, name)` et `add_min_score(constraints, name, score)`.
Pas destiné à être exécuté directement.

### `solver.py`
`RelaySolver` : itérateur streaming sur les solutions CP-SAT (thread séparé).
Écrit le planning dans `plannings/` (`.txt`, `.csv`, `.json` et `.html`).

```bash
python solver.py
```

### `solution.py`
`RelaySolution` : encapsule une solution avec vérification automatique et formatage.
API : `to_text()`, `to_csv()`, `to_json()`, `to_html()`, `save(verbose=)`, `stats()`.
`stats()` retourne `(n_binomes, n_solos, km_solos, n_flex, n_fixes, km_flex)` (`km_flex` = km économisés par les relais flex).
Le HTML inclut une grille Gantt par coureur (vert = binôme, rose = solo, bleu = relais fixe,
gris = repos minimal, violet = indisponible) avec repères toutes les 6h. Coureurs triés alphabétiquement.

### `verifications.py`
Suite de vérifications post-résolution : couverture, tailles des relais, contraintes de repos,
limites nuit/solo, pairings, compatibilité, et franchissement de frontières de pause.

### `refresh_compat.py`
Relit `compat_coureurs.xlsx` et régénère `compat.py`. Valide la structure de la matrice
(carrée, symétrique, diagonale = `X`, triangle inférieur uniquement).

```bash
python refresh_compat.py
```

### `utils/feasibility_analyser.py`
`FeasibilityAnalyser` : diagnostique automatiquement les contraintes causant l'infaisabilité
d'un modèle. Stratégie en trois phases :

1. **Modèle complet** — si faisable, aucun problème.
2. **Désactivation par famille** — teste chaque groupe de contraintes isolément
   (pinned, nuit_max, repos, disponibilités, couverture, no-overlap, solo, pairings forcés,
   `add_max_binomes`, `max_same_partenaire`). Les familles dont la désactivation rend le
   modèle faisable sont marquées suspectes.
3. **Diagnostic fin** — pour chaque famille suspecte, identifie les coureurs ou relais
   responsables (test coureur par coureur, pairing par pairing, contrainte par contrainte).
   Si aucune famille seule ne suffit, une phase bonus teste toutes les paires de familles.

Fonction utilitaire : `analyse(constraints, timeout=10.0)`.
Les timeouts sont traités comme faisables (pas de preuve d'infaisabilité sans résolution complète).

```bash
python utils/feasibility_analyser.py
```

## Sorties

| Dossier / fichier  | Contenu                                                               |
|--------------------|-----------------------------------------------------------------------|
| `plannings/`       | Plannings `.txt`, `.csv`, `.json` et `.html` produits par `solver.py` |

## Documentation

- [CONSTRAINTS.md](CONSTRAINTS.md) — Référence complète de l'API de déclaration des contraintes

## Licence

MIT — voir [LICENSE](LICENSE).
