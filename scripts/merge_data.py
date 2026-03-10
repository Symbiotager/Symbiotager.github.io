#!/usr/bin/env python3
"""
Merge PAUT formatted data with the original Google Sheets data (especes_v2 + associations).
Deduplicates species, merges interactions, prunes weak entries,
and optionally enriches with NCBI/Wikipedia data.

Reads from data/:
  - paut_formatted_especes.csv, paut_formatted_associations.csv  (primary)
  - especes_v2.csv, associations.csv                              (secondary)

Produces in data/:
  - merged_especes.csv, merged_associations.csv

Run from repo root: python scripts/merge_data.py
"""

import csv
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from scripts.constants import *
from scripts.function_search_taxonomy import enrich_species_db

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')

# The source will be merged into the target
species_to_merge = [
    ("achillée", "achillée millefeuille"),
    ("céleri", "céleris"),
    ("céleri branche", "céleris"),
    ("céleri-rave", "céleris"),
    ("cerise", "cerisier"),
    ("fraise", "fraisier"),
    ("framboise", "framboisier"),
    ("groseille", "groseillier"),
    ("haricot", "haricots"),
    ("haricot vert", "haricots"),
    ("haricot à ecosser et demi-secs", "haricots"),
    ("haricot de guar", "haricots"),
    ("laurier-sauce", "laurier sauce"),
    ("poire", "poirier"),
    ("poires d'automne", "poirier"),
    ("poires d'ete autres", "poirier"),
    ("poires d'hiver", "poirier"),
    ("poires jules guyot", "poirier"),
    ("poires william's", "poirier"),
    ("pomme", "pommier"),
    ("pomme golden", "pommier"),
    ("pomme granny smith", "pommier"),
    ("pomme de table autres", "pommier"),
    ("prune", "prunier"),
    ("prunes autres", "prunier"),
    ("pêche", "pêcher"),
    ("féverole", "fève fèverole"),
]

species_to_remove = [
    "agrumes",
    "arbres fruitiers",
]


# ---------------------------------------------------------------------------
# In-memory storage
# ---------------------------------------------------------------------------

species_db = {}       # name → {common_name, category, wiki, taxonomy, latin_name, TaxID, NCBI}
interactions_db = {}  # (source, target) → {interaction: str, references: str, weight: float}


def add_or_update_specie(name, common_name, category, latin_name='', wiki='', taxonomy='', TaxID='', NCBI=''):
    name = clean_string(name)
    if not name or len(name) < 3:
        return
    if category not in categories.values():
        print(FAIL + f"Invalid category '{category}' for species '{name}'" + ENDC)
        return
    if name not in species_db:
        species_db[name] = {
            'common_name': clean_string(common_name),
            'category': clean_string(category),
            'wiki': clean_string(wiki),
            'taxonomy': clean_string(taxonomy),
            'latin_name': clean_string(latin_name),
            'TaxID': clean_string(str(TaxID)) if TaxID else '',
            'NCBI': clean_string(NCBI),
        }
    else:
        existing = species_db[name]
        existing['common_name'] = most_complete(existing['common_name'], clean_string(common_name))
        existing['category'] = most_complete(existing['category'], clean_string(category))
        existing['wiki'] = most_complete(existing['wiki'], clean_string(wiki))
        existing['taxonomy'] = most_complete(existing['taxonomy'], clean_string(taxonomy))
        existing['latin_name'] = most_complete(existing['latin_name'], clean_string(latin_name))
        if TaxID:
            existing['TaxID'] = clean_string(str(TaxID))
        if NCBI:
            existing['NCBI'] = most_complete(existing['NCBI'], clean_string(NCBI))


def add_or_update_interaction(source, target, interaction, references='', weight=1.0):
    if source not in species_db:
        return
    if target not in species_db:
        return
    if source == target:
        return

    # Plant/animal interactions get a boosted weight
    if species_db[source]['category'] in cat_animals or species_db[target]['category'] in cat_animals:
        weight = max(weight, 9.0)

    key = (source, target)
    if key not in interactions_db:
        interactions_db[key] = {
            'interaction': interaction,
            'references': references,
            'weight': weight,
        }
    else:
        existing = interactions_db[key]
        if references and references in existing['references']:
            return
        if existing['interaction'] == interaction:
            existing['weight'] += weight
        else:
            existing['weight'] -= weight
        if references:
            existing['references'] += f", {references}"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def populate_from_csv(especes_file, associations_file):
    """Load species and associations from CSV files into the in-memory stores."""
    print(f"Loading species from {especes_file}...")
    with open(especes_file, 'r', newline='', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter=',', quotechar='"')
        next(reader)
        for line in reader:
            if len(line) < 8:
                continue
            add_or_update_specie(
                name=clean_string(line[7]),
                common_name=clean_string(line[0]),
                category=clean_string(line[1]),
                wiki=clean_string(line[2]),
                taxonomy=clean_string(line[3]),
                latin_name=clean_string(line[4]),
                TaxID=clean_string(line[5]),
                NCBI=clean_string(line[6]),
            )

    print(f"Loading associations from {associations_file}...")
    with open(associations_file, 'r', newline='', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter=',', quotechar='"')
        next(reader)
        for row in reader:
            if len(row) < 3:
                continue
            source = clean_string(row[0])
            assoc_str = clean_string(row[1])
            target = clean_string(row[2])
            references = clean_string(row[3]) if len(row) > 3 else ''
            weight_str = clean_string(row[4]) if len(row) > 4 else ''

            if assoc_str not in description_interactions:
                continue

            inter_int = description_interactions[assoc_str]
            interaction = interactions[inter_int]
            weight = float(weight_str) if weight_str else 1.0

            add_or_update_interaction(
                source=source, target=target, interaction=interaction,
                references=references, weight=weight,
            )


# ---------------------------------------------------------------------------
# Species operations
# ---------------------------------------------------------------------------

def remove_species(species_name):
    if species_name not in species_db:
        print(f"Species '{species_name}' not found.")
        return
    del species_db[species_name]
    to_delete = [k for k in interactions_db if k[0] == species_name or k[1] == species_name]
    for k in to_delete:
        del interactions_db[k]
    print(f"Removed species '{species_name}' and {len(to_delete)} interactions.")


def merge_species(source_name, target_name):
    if source_name not in species_db:
        return
    if target_name not in species_db:
        return
    print(f"Merging '{source_name}' → '{target_name}'")

    # Redirect interactions where source_name is the source
    keys_as_source = [k for k in interactions_db if k[0] == source_name]
    for key in keys_as_source:
        data = interactions_db.pop(key)
        new_target = key[1]
        if new_target == target_name:
            continue
        add_or_update_interaction(
            source=target_name, target=new_target,
            interaction=data['interaction'], references=data['references'], weight=data['weight'],
        )

    # Redirect interactions where source_name is the target
    keys_as_target = [k for k in interactions_db if k[1] == source_name]
    for key in keys_as_target:
        data = interactions_db.pop(key)
        new_source = key[0]
        if new_source == target_name:
            continue
        add_or_update_interaction(
            source=new_source, target=target_name,
            interaction=data['interaction'], references=data['references'], weight=data['weight'],
        )

    # Remove the source species
    if source_name in species_db:
        del species_db[source_name]


def prune_associations():
    """Remove zero-weight, invert negative-weight interactions."""
    reverse_map = {'pos': 'neg', 'neg': 'pos', 'atr': 'rep', 'rep': 'atr'}
    to_delete = []
    for key, data in interactions_db.items():
        if data['weight'] == 0:
            to_delete.append(key)
        elif data['weight'] < 0:
            data['interaction'] = reverse_map[data['interaction']]
            data['weight'] = -data['weight']
    for key in to_delete:
        del interactions_db[key]


def prune_species():
    """Remove species that have no interactions."""
    species_with_interactions = set()
    for (s, t) in interactions_db:
        species_with_interactions.add(s)
        species_with_interactions.add(t)
    to_delete = [name for name in species_db if name not in species_with_interactions]
    for name in to_delete:
        del species_db[name]
    if to_delete:
        print(f"Pruned {len(to_delete)} species with no interactions.")


def prune_db():
    prune_associations()
    prune_species()


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------

def save_species_csv(filepath):
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        writer.writerow(['common_name', 'category', 'wiki', 'taxonomy', 'latin_name', 'TaxID', 'NCBI', 'name'])
        for name in sorted(species_db.keys()):
            sp = species_db[name]
            writer.writerow([
                sp['common_name'], sp['category'], sp['wiki'], sp['taxonomy'],
                sp['latin_name'], sp['TaxID'], sp['NCBI'], name,
            ])


def save_associations_csv(filepath):
    inter_label = {'pos': 'favorise', 'neg': 'défavorise', 'atr': 'attire', 'rep': 'repousse'}
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        writer.writerow(['espèce source', 'interaction', 'espèce cible', 'source', 'poids', 'commentaire'])
        for (source, target), data in sorted(interactions_db.items()):
            writer.writerow([
                source, inter_label[data['interaction']], target,
                data['references'], data['weight'], '',
            ])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global species_db, interactions_db
    species_db = {}
    interactions_db = {}

    # 1. Load primary data (PAUT formatted)
    populate_from_csv(
        os.path.join(DATA_DIR, 'paut_formatted_especes.csv'),
        os.path.join(DATA_DIR, 'paut_formatted_associations.csv'),
    )
    print(f"After PAUT: {len(species_db)} species, {len(interactions_db)} interactions")

    # 2. Merge secondary data (Google Sheets)
    populate_from_csv(
        os.path.join(DATA_DIR, 'especes_v2.csv'),
        os.path.join(DATA_DIR, 'associations.csv'),
    )
    print(f"After merge: {len(species_db)} species, {len(interactions_db)} interactions")

    # 3. Merge similar species
    print("\nMerging similar species...")
    for source, target in species_to_merge:
        merge_species(source, target)

    # 4. Remove unwanted species
    print("\nRemoving unwanted species...")
    for name in species_to_remove:
        remove_species(name)

    # 5. Prune
    print(f"Before pruning: {len(species_db)} species, {len(interactions_db)} interactions")
    prune_db()
    print(f"After pruning: {len(species_db)} species, {len(interactions_db)} interactions")

    # 6. Enrich with NCBI/Wikipedia taxonomy data
    print("\nEnriching species with Wikipedia/NCBI data...")
    enrich_species_db(species_db, clean_string)

    # 7. Save
    save_species_csv(os.path.join(DATA_DIR, 'merged_especes.csv'))
    save_associations_csv(os.path.join(DATA_DIR, 'merged_associations.csv'))
    print(OKGREEN + "Done. Output written to data/merged_*.csv" + ENDC)


if __name__ == '__main__':
    main()
