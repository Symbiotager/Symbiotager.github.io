[![License: CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc-sa/4.0/)

# Symbiotager

Symbiotager est une application web statique permettant de simuler son potager en insérant les diverses espèces de fruits et légumes, et de savoir si les interactions seront favorables ou défavorables. Symbiotager permet également d'obtenir facilement des informations sur la façon dont un parasite peut être éliminé par des plants compagnes.

Deux versions du site sont générées :
- **Version Paut** (par défaut, `index.html`) — données issues du projet Paut, avec poids des sources et interactivité sur les liens
- **Version originale** (`MonPotager.html`) — données issues des Google Sheets

## Structure du projet

```
Symbiotager/
├── data/                       # Données CSV (espèces et interactions)
│   ├── paut_formatted_especes.csv
│   ├── paut_formatted_associations.csv
│   ├── paut_references.csv     # Références bibliographiques Paut
│   ├── especes_v2.csv
│   ├── associations.csv
│   └── ...
├── scripts/                    # Scripts Python
│   ├── generate.py             # Générateur de site statique
│   ├── constants.py            # Constantes partagées (couleurs, catégories)
│   ├── format_paut_data.py     # Formatage des données Paut brutes
│   └── merge_data.py           # Fusion des données Paut + Google Sheets
├── templates/                  # Sources des assets et template HTML
│   ├── MonPotager.html         # Template Jinja2
│   ├── MonPotager.css.scss     # SCSS source
│   ├── js/                     # JS source et librairies vendor
│   ├── css/                    # CSS vendor (Bootstrap)
│   └── fonts/                  # Polices (Glyphicons)
├── .github/workflows/
│   └── deploy.yml              # GitHub Action : build + déploiement
├── push_main_website.sh        # Script de déploiement local
├── requirements.txt
├── .gitignore
├── LICENSE.md
└── README.md
```

## Utilisation locale

### Prérequis

Python 3.10+

### Installation

```bash
git clone https://github.com/ThibaultLatrille/Symbiotager
cd Symbiotager
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Génération du site

```bash
python -m scripts.generate
```

Cela produit :
- `index.html` — version Paut
- `MonPotager.html` — version originale
- `static/` — CSS, JS, polices, images

### Serveur local

```bash
python -m http.server 8000
```

Puis ouvrir http://localhost:8000/

## Déploiement

Le projet utilise deux branches Git :
- **`main`** — code source (sans les fichiers générés, ignorés par `.gitignore`)
- **`website`** — fichiers générés déployés via GitHub Pages

### Déploiement automatique

Un push sur `main` déclenche le workflow GitHub Actions (`.github/workflows/deploy.yml`) qui :
1. Rebase `website` sur `main`
2. Génère le site
3. Force-push `website`

### Déploiement manuel

```bash
bash push_main_website.sh
```

## Fonctionnalités spécifiques à la version Paut

La version Paut (`index.html`) dispose de fonctionnalités supplémentaires exploitant les références bibliographiques du projet Paut :

- **Épaisseur des liens** — les flèches d'interaction ont une épaisseur proportionnelle au nombre de sources (3 niveaux : fin ≤ 2, moyen 3–5, épais ≥ 6)
- **Infobulle au survol** — au passage de la souris sur un lien, une infobulle affiche le nombre de sources en accord et en désaccord avec l'interaction
- **Panneau de détail au clic** — un clic sur un lien affiche dans le panneau latéral la liste complète des références (avec liens vers les sources), en distinguant celles en accord (vert) et en désaccord (rouge)

Ces données sont calculées à partir de `data/paut_references.csv` et des champs `references` et `weight` présents dans `data/paut_formatted_associations.csv`.

## Préparation des données

Les scripts dans `scripts/` permettent de transformer les données brutes CSV :

- `format_paut_data.py` — formate les données brutes du projet Paut (`data/paut_*.csv`) en `data/paut_formatted_*.csv`. Gère le sens directionnel des associations (colonne `Sens`) et valide les identifiants de références.
- `merge_data.py` — fusionne les données Paut et Google Sheets en `data/merged_*.csv`

## Contribuer

Si vous souhaitez ajouter des fonctionnalités ou corriger des bugs, n'hésitez pas à ouvrir une [pull-request](https://github.com/ThibaultLatrille/Symbiotager/pulls).
Pour signaler un problème, ouvrez une [issue](https://github.com/ThibaultLatrille/Symbiotager/issues).

## Licence

Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0). Voir [LICENSE.md](LICENSE.md) pour plus d'informations.
