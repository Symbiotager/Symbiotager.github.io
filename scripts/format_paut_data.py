#!/usr/bin/env python3
"""
Format raw PAUT data into the standardized CSV format for MonPotager.
Reads paut_especes.csv, paut_associations.csv, paut_references.csv from data/.
Produces paut_formatted_especes.csv and paut_formatted_associations.csv in data/.

Run from repo root: python scripts/format_paut_data.py
"""

import csv
import os
import re
import sys

import polars as pl

# Ensure scripts/ is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from scripts.constants import *
from scripts.function_search_taxonomy import enrich_species_db

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')

# Mapping from +/- to interaction string codes
interaction_mapping = {
    '+': 'pos',
    '-': 'neg',
}

# Mapping from PAUT crop types to French categories
category_mapping = {
    'Vegetable': 'Légume',
    'Fruit': 'Fruit',
    'Medicinal, Aromatic Plants, Flowers & Others': 'Arômate',
    'Vegetables': 'Légume',
    'Fruits': 'Fruit',
    'Shrubs & Berries': 'Fruit',
    'Trees (woody perennials)': 'Arbres',
    'Cereals': 'Céréale',
}


def clean_name(name):
    name = re.sub(r'\([^)]*\)', '', name)
    name = re.sub(r'[&…]', ' ', name)
    name = re.sub(r'\s+', ' ', name)
    if 'petits pois' in name.lower():
        name = name.lower().replace('petits pois', 'pois')
    if 'chou brocoli' in name.lower():
        name = name.lower().replace('chou brocoli', 'brocoli')
    return name.strip().capitalize()


def load_reference_names():
    filepath = os.path.join(DATA_DIR, 'paut_references.csv')
    df = pl.read_csv(filepath, encoding='utf-8')
    print(f"Loading reference names from paut_references.csv...")
    print(f"Columns in paut_references.csv: {df.columns}")

    reference_map = {}
    for row in df.to_dicts():
        ref_id = row.get('Pages internet', '')
        ref_name = row.get('', '')
        if ref_id and ref_name and ref_id not in ('id', 'Ouvrages', 'Outlis et applications'):
            if ref_id == 'à faire' or '(' in ref_id:
                continue
            try:
                int(ref_id)
                reference_map[str(ref_id)] = f"'{ref_name}'"
            except ValueError:
                continue
    return reference_map


# ---------------------------------------------------------------------------
# In-memory species and interaction storage
# ---------------------------------------------------------------------------

species_db = {}  # name → {common_name, category, wiki, taxonomy, latin_name, TaxID, NCBI}
interactions_db = {}  # (source, target) → {interaction, references, weight}


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
            'TaxID': clean_string(str(TaxID)),
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
        print(FAIL + f"Source species '{source}' not found, skipping interaction." + ENDC)
        return
    if target not in species_db:
        print(FAIL + f"Target species '{target}' not found, skipping interaction." + ENDC)
        return
    if source == target:
        return

    key = (source, target)
    if key not in interactions_db:
        interactions_db[key] = {
            'interaction': interaction,
            'references': references,
            'weight': weight,
        }
    else:
        existing = interactions_db[key]
        if references in existing['references']:
            return
        if existing['interaction'] == interaction:
            existing['weight'] += weight
        else:
            # Opposite interaction: subtract
            existing['weight'] -= weight
        existing['references'] += f", {references}"


def prune_associations():
    to_delete = []
    reverse_map = {'pos': 'neg', 'neg': 'pos', 'atr': 'rep', 'rep': 'atr'}
    for key, data in interactions_db.items():
        if data['weight'] == 0:
            to_delete.append(key)
        elif data['weight'] < 0:
            data['interaction'] = reverse_map[data['interaction']]
            data['weight'] = -data['weight']
    for key in to_delete:
        del interactions_db[key]


# ---------------------------------------------------------------------------
# Data processing
# ---------------------------------------------------------------------------

def clean_species_data():
    filepath = os.path.join(DATA_DIR, 'paut_especes.csv')
    df = pl.read_csv(filepath, encoding='utf-8')

    for row in df.to_dicts():
        french_name = str(row.get('Crop_fr', '')).strip()
        if french_name == 'None':
            continue

        latin_name = str(row.get('Latin_name', '')).strip()
        if not latin_name:
            latin_name = 'nom latin non trouvé'

        crop_type_rp = str(row.get('Crop_type_RP', '')).strip()
        crop_type_pennington = str(row.get('Crop_type_Pennington_2009', '')).strip()
        raw_category = crop_type_rp or crop_type_pennington
        category = category_mapping.get(raw_category, 'Légume')

        common_name = clean_name(french_name).lower()
        taxonomy = row.get('Crop_family', '').strip() if row.get('Crop_family') else ''
        add_or_update_specie(common_name=common_name, category=category, taxonomy=taxonomy,
                             latin_name=latin_name, name=common_name)


def clean_associations_data():
    filepath = os.path.join(DATA_DIR, 'paut_associations.csv')
    df = pl.read_csv(filepath, encoding='utf-8')

    unique_associations = df.group_by(['crop1', 'crop2', 'source']).agg(
        pl.col('type').mode().first().alias('type'),
        pl.col('Sens').mode().first().alias('Sens'),
        pl.col('Reason').mode().first().alias('Reason'),
    ).sort(['crop1', 'crop2'])
    print(f"Original associations count: {len(df)}")
    print(f"Unique associations count after collapsing: {len(unique_associations)}")

    reference_map = load_reference_names()

    for row in unique_associations.to_dicts():
        source_raw = row.get('crop1', '').strip()
        target_raw = row.get('crop2', '').strip()
        interaction_type = str(row.get('type', '')).strip()

        if not source_raw or not target_raw or not interaction_type:
            continue

        source = clean_name(source_raw).lower()
        target = clean_name(target_raw).lower()
        interaction = interaction_mapping[interaction_type]

        source_num = str(row.get('source', '')).strip()
        reference_name = reference_map.get(source_num, None)
        if reference_name is None:
            print(WARNING + f"Reference ID '{source_num}' not found in paut_references.csv" + ENDC)
            reference_name = f"une autre source ({source_num})"
        reference = f"{interaction_forward[interaction]} d'après {reference_name}"

        direction = str(row.get('Sens', '')).strip()
        if direction == '' or direction == 'null' or direction == 'None':
            add_or_update_interaction(source=source, target=target, interaction=interaction, references=reference)
            add_or_update_interaction(source=target, target=source, interaction=interaction, references=reference)
        elif direction[0] == '1' and direction[-1] == '2':
            add_or_update_interaction(source=source, target=target, interaction=interaction, references=reference)
        elif direction[0] == '2' and direction[-1] == '1':
            add_or_update_interaction(source=target, target=source, interaction=interaction, references=reference)
        else:
            print(WARNING + f"Unknown direction '{direction}' for {source} → {target}, treating as bidirectional." + ENDC)
            add_or_update_interaction(source=source, target=target, interaction=interaction, references=reference)
            add_or_update_interaction(source=target, target=source, interaction=interaction, references=reference)


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
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        writer.writerow(['espèce source', 'interaction', 'espèce cible', 'source', 'poids', 'commentaire'])
        inter_label = {'pos': 'favorise', 'neg': 'défavorise', 'atr': 'attire', 'rep': 'repousse'}
        for (source, target), data in sorted(interactions_db.items()):
            writer.writerow([
                source, inter_label[data['interaction']], target,
                data['references'], data['weight'], '',
            ])


def main():
    global species_db, interactions_db
    species_db = {}
    interactions_db = {}

    print("Processing PAUT species data...")
    clean_species_data()
    print(f"Species count: {len(species_db)}")

    print("Processing PAUT associations data...")
    clean_associations_data()
    print(f"Associations count: {len(interactions_db)}")

    neg_count = sum(1 for d in interactions_db.values() if d['weight'] <= 0)
    print(f"Interactions with 0 or negative weight: {neg_count}")
    prune_associations()
    print(f"Associations count after pruning: {len(interactions_db)}")

    # Enrich species with Wikipedia and NCBI taxonomy data
    print("\nEnriching species with Wikipedia/NCBI data...")
    enrich_species_db(species_db, clean_string)

    save_species_csv(os.path.join(DATA_DIR, 'paut_formatted_especes.csv'))
    save_associations_csv(os.path.join(DATA_DIR, 'paut_formatted_associations.csv'))
    print(OKGREEN + "Done. Output written to data/paut_formatted_*.csv" + ENDC)


if __name__ == '__main__':
    main()
