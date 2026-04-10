# Guide de dépannage (ERRORS.md)

Ce guide couvre les erreurs les plus courantes et comment les résoudre.

## Table des matières

1. [Erreurs de configuration](#erreurs-de-configuration)
2. [Erreurs de fichiers](#erreurs-de-fichiers)
3. [Erreurs de résolution](#erreurs-de-résolution)
4. [Erreurs de performance](#erreurs-de-performance)

---

## Erreurs de configuration

### ❌ "Coureur 'X' n'a pas de relais"

**Cause** : Un coureur a été créé avec `new_runner()` mais aucun relais ne lui a été assigné.

**Solution** :
```python
# ❌ INCORRECT
pascal = c.new_runner("Pascal", lvl=3)
# Pascal n'a pas de relais → ERREUR

# ✅ CORRECT
pascal = c.new_runner("Pascal", lvl=3)
pascal.add_relay(R20)  # Ajouter au moins un relais
```

Alternativement, retirer le coureur de la configuration s'il n'a rien à faire.

---

### ❌ "Coureur 'X' absent de la matrice de compatibilité"

**Cause** : Un coureur a été créé avec `new_runner()` mais ne figure pas dans le fichier de compatibilité.

**Solution** :

1. Vérifier que le nom du coureur existe dans `compat_coureurs.xlsx` (colonne A)
2. Vérifier l'orthographe exacte (majuscules/minuscules)
3. Si le coureur est nouveau, ajouter une ligne dans `compat_coureurs.xlsx`

```python
# ❌ INCORRECT
pascal = c.new_runner("pascal", lvl=3)  # "pascal" n'existe pas dans XLSX

# ✅ CORRECT
pascal = c.new_runner("Pascal", lvl=3)  # Respecter la casse exacte
```

---

### ❌ "Relais X : min_m > max_m"

**Cause** : Le relais a une distance minimale plus grande que la distance maximale.

**Solution** :
```python
# ❌ INCORRECT
R20 = Preset(km=20, min=25, max=18)  # min > max

# ✅ CORRECT
R20 = Preset(km=20, min=18, max=25)  # min ≤ max
```

**Rappel** : `Preset(km, min, max)` — les deux derniers sont optionnels mais doivent respecter `min ≤ max`.

---

### ❌ "Window invalide (lo > hi)"

**Cause** : Une fenêtre temporelle ou spatiale a été définie à l'envers.

**Solution** :
```python
# ❌ INCORRECT
pascal.add_relay(R20, window=c.interval_km(100, 50))  # 100 > 50

# ✅ CORRECT
pascal.add_relay(R20, window=c.interval_km(50, 100))  # 50 ≤ 100
```

**Pour les heures** :
```python
# ❌ INCORRECT
c.interval_time(18.0, 0, 9.0, 0)  # 18h jour0 > 9h jour0

# ✅ CORRECT (même jour)
c.interval_time(9.0, 0, 18.0, 0)  # 9h jour0 < 18h jour0

# ✅ CORRECT (sur deux jours)
c.interval_time(22.0, 0, 6.0, 1)  # 22h jour0 < 6h jour1
```

---

### ❌ "solo_max_km > parcours total"

**Cause** : Un coureur ne peut pas faire seul plus que la totalité du parcours.

**Solution** :
```python
# ❌ INCORRECT
c = Constraints(..., solo_max_km=500)  # Parcours = 440 km

# ✅ CORRECT
c = Constraints(..., solo_max_km=50)  # 50 km max en solo
```

---

### ❌ "SharedLeg doit être affecté à exactement 2 coureurs"

**Cause** : Un relais partagé a été créé avec `new_shared_relay()` mais n'a été ajouté que pour 1 coureur (ou 3+).

**Solution** :
```python
# Créer un relais partagé
shared = c.new_shared_relay(R20)

# L'ajouter à EXACTEMENT 2 coureurs
pascal = c.new_runner("Pascal", lvl=3)
marie = c.new_runner("Marie", lvl=3)

pascal.add_relay(shared)  # 1er coureur
marie.add_relay(shared)   # 2e coureur
# Pas d'ajout pour un 3e → OK

# ❌ ERREUR si pascal ou marie n'a pas add_relay(shared)
```

---

## Erreurs de fichiers

### ❌ "Fichier manquant : [chemin]"

**Cause** : Un fichier requis ne peut pas être lu.

**Solution** :

1. Vérifier que le fichier existe
2. Vérifier le chemin dans `example.py`
3. Les chemins doivent être relatifs au répertoire racine

```python
# ❌ Chemin incorrect (relatif au dossier courant, pas au projet)
c = Constraints(
    parcours="gpx/parcours.gpx",  # OK si lancé depuis la racine
    compat_matrix="compat_coureurs.xlsx"
)

# ✅ Chemin absolu (plus robuste)
from pathlib import Path
root = Path(__file__).parent
c = Constraints(
    parcours=root / "gpx/parcours.gpx",
    compat_matrix=root / "compat_coureurs.xlsx"
)
```

**Pour exécuter correctement** :
```bash
cd /home/vintz/projets/relais-planner  # Aller à la racine du projet
python example.py                       # Lancer depuis la racine
```

---

### ❌ "Impossible de lire XLSX. Sauvegarder en UTF-8"

**Cause** : Le fichier `compat_coureurs.xlsx` a un encodage incompatible ou est corrompu.

**Solution** :

1. Ouvrir `compat_coureurs.xlsx` dans Excel ou LibreOffice
2. Vérifier que la structure est correcte :
   - Colonne A : noms des coureurs
   - Ligne 1 : en-têtes
   - Cellules : notes de compatibilité (nombres entiers 0-100)
3. Enregistrer en UTF-8 (défaut dans Excel/LibreOffice modernes)
4. Relancer le script

---

### ❌ "Impossible de charger GPX"

**Cause** : Le fichier GPX est invalide ou absent.

**Solution** :

1. Vérifier que `gpx/parcours.gpx` existe
2. Vérifier que le fichier est un GPX valide (structure XML)
3. S'il vient d'un export, vérifier qu'il contient les éléments `<trkpt>` (waypoints)

```bash
# Vérifier la structure (d'abord quelques lignes)
head -20 gpx/parcours.gpx
```

---

## Erreurs de résolution

### ❌ "Configuration invalide : [détail]"

**Cause** : La configuration des relais viole une contrainte logique.

**Solutions possibles** :

1. **Vérifier la couverture** : Chaque arc doit être couvert par exactement 1-2 relais
   ```python
   # Afficher la couverture estimée
   python example.py data
   ```

2. **Ajuster les fenêtres** : Si un relais a une fenêtre trop restrictive
   ```python
   # ❌ Trop restrictif
   pascal.add_relay(R20, window=c.interval_km(100, 105))
   
   # ✅ Plus flexible
   pascal.add_relay(R20, window=c.interval_km(80, 120))
   ```

3. **Réduire les contraintes** : Augmenter les marges de distance/temps
   ```python
   # Relâcher les limites solo/nuit
   pascal.set_options(solo_max=50, nuit_max=50)
   ```

---

### ❌ "Modèle infaisable. Utiliser : `python exemple.py diag`"

**Cause** : Aucune solution ne satisfait l'ensemble des contraintes.

**Solution** :

Lancer l'analyseur de faisabilité pour identifier quelle(s) contrainte(s) pose(nt) problème :

```bash
python example.py diag
```

Cet outil :
- Désactive chaque contrainte une à une
- Teste si le modèle devient faisable
- Vous rapporte les contraintes problématiques

**Actions possibles** :

1. **Augmenter les marges** : si c'est un problème de fenêtre/temps
   ```python
   c.add_night(c.interval_time(23.0, 0, 6.0, 1))  # Adapter aux effectifs
   ```

2. **Épingler moins de relais** : libérer des degrés de liberté
   ```python
   # Retirer des start_km/end_km
   ```

3. **Augmenter les temps de repos** : si c'est un problème de disponibilité
   ```python
   c = Constraints(..., repos_jour_heures=2, repos_nuit_heures=4)
   ```

---

### ❌ "Timeout après Xmin. Aucune solution trouvée."

**Cause** : Le solveur a atteint son temps limite sans trouver de solution.

**Solutions** :

1. **Augmenter le timeout** (par défaut : illimité via `timeout_sec=0`)
   ```bash
   python example.py solve  # Laisse tourner plus longtemps
   ```

2. **Simplifier le modèle** :
   - Réduire le nombre de coureurs
   - Augmenter les marges de distance/temps
   - Retirer les contraintes non essentielles

3. **Utiliser un hint** : fournir une solution antérieure comme point de départ
   ```bash
   python example.py solve --ref planning.json
   ```

---

### ❌ "Score optimal inférieur à --min-score"

**Cause** : Le solveur n'a pas pu trouver une solution avec le score requis.

**Solution** :

Vérifier le score possible avec `python example.py data`, puis ajuster :

```bash
# Vérifier les contraintes de score
python example.py solve --min-score 85  # Adapter le nombre
```

---

## Erreurs de performance

### ⏳ "La résolution prend très longtemps (> 30 min)"

**Cause** : Le modèle est complexe ou le solveur explore trop d'options.

**Solutions** :

1. **Utiliser un hint** : démarre le solveur avec une bonne solution
   ```bash
   python example.py solve --ref planning.json
   ```

2. **Ajouter des contraintes** : réduire l'espace de recherche
   ```python
   # Épingler certains relais pour les aider
   pascal.add_relay(R20, window=c.interval_km(50, 100))
   ```

3. **Réduire la complexité** :
   - Moins de coureurs
   - Moins de choix de relais par coureur
   - Marges fixes au lieu de gammes larges

---

### 📊 "Comment comprendre le score de sortie?"

**Score binôme (duos)** :
- Somme des compatibilités pour les binômes effectués
- Basé sur la matrice `compat_coureurs.xlsx`
- Plus c'est haut, meilleur c'est

**Solos** :
- Nombre de relais en solo + distance cumulée
- Idéalement : minimiser les solos

**D+/D-** (si --dplus) :
- Dénivelé positif/négatif cumulé
- Pondéré par le niveau du coureur (lvl)

---

## Besoin d'aide supplémentaire?

Si votre problème ne figure pas ici :

1. Vérifier les messages d'erreur exactement (copy-coller)
2. Essayer `python example.py diag` pour analyser la faisabilité
3. Consulter le rapport dans `plannings/<YYYYMMDD_HHMMSS>/planning.txt`
4. Signaler le bug avec :
   - Votre `example.py`
   - Les fichiers de configuration (GPX, XLSX)
   - Les messages d'erreur complets

