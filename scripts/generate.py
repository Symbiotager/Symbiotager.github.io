#!/usr/bin/env python3
"""
Static site generator for MonPotager.
Reads CSV data files and Jinja2 templates, produces two HTML versions:
  - index.html       (Paut data, default)
  - MonPotager.html   (Original Google Sheets data)
along with their respective data JS files and shared static assets.
"""

import csv
import json
import os
import re
import shutil
from datetime import datetime

import jinja2
import sass
from jsmin import jsmin

from scripts.constants import (
    ENDC, OKBLUE, OKGREEN,
    cat_animals, cat_pests, cat_plants,
    categories, color, description_interactions,
    interaction_backward, interaction_forward, interactions,
    reverse_cat, reverse_dict, reverse_interactions, clean_string,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(ROOT_DIR, "data")
TEMPLATES_DIR = os.path.join(ROOT_DIR, "templates")
STATIC_DIR = os.path.join(ROOT_DIR, "static")


# ---------------------------------------------------------------------------
# CSV reading
# ---------------------------------------------------------------------------

def read_species_csv(filepath):
    """
    Read a species CSV file and return a dict keyed by species name.
    Handles both paut_formatted (clean headers) and especes_v2 (French headers with spaces).
    Each value is a dict with keys: common_name, category, wiki, taxonomy, latin_name, TaxID, NCBI.
    """
    species = {}
    with open(filepath, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=",", quotechar='"')
        next(reader)  # skip header
        for row in reader:
            if len(row) < 8:
                continue
            name = clean_string(row[7])
            if not name:
                continue
            species[name] = {
                "common_name": clean_string(row[0]),
                "category": clean_string(row[1]),
                "wiki": clean_string(row[2]),
                "taxonomy": clean_string(row[3]),
                "latin_name": clean_string(row[4]),
                "TaxID": clean_string(row[5]),
                "NCBI": clean_string(row[6]),
            }
    return species


def read_associations_csv(filepath, valid_species):
    """
    Read an associations CSV file and return a list of tuples.
    Returns (source, interaction_int, target, references_str, weight).
    Only includes associations where both source and target exist in valid_species.
    """
    assocs = []
    with open(filepath, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=",", quotechar='"')
        next(reader)  # skip header
        for row in reader:
            if len(row) < 3:
                continue
            source = clean_string(row[0])
            inter_str = clean_string(row[1])  # e.g. "favorise", "défavorise", "attire", "repousse"
            target = clean_string(row[2])

            if source not in valid_species:
                continue
            if target not in valid_species:
                continue
            if inter_str not in description_interactions:
                continue

            inter_int = description_interactions[inter_str]
            references = clean_string(row[3]) if len(row) > 3 else ''
            weight = float(clean_string(row[4])) if len(row) > 4 and clean_string(row[4]) else 1.0
            assocs.append((source, inter_int, target, references, weight))
    return assocs


def filter_species_with_associations(species, associations):
    """Remove species that have no associations at all."""
    has_assoc = set()
    for source, _, target, _, _ in associations:
        has_assoc.add(source)
        has_assoc.add(target)
    removed = {name for name in species if name not in has_assoc}
    if removed:
        print(f"Removed {len(removed)} species with no associations")
    return {name: sp for name, sp in species.items() if name in has_assoc}


def read_references_csv(filepath):
    """
    Read paut_references.csv and return a dict mapping reference display name to URL.
    """
    refs = {}
    with open(filepath, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=",", quotechar='"')
        current_section = None
        for row in reader:
            if len(row) < 3:
                continue
            col0 = row[0].strip()
            if col0 in ('Pages internet', 'Ouvrages', 'Outlis et applications'):
                current_section = col0
                continue
            if col0 == 'id' or col0 == 'à faire' or col0 == '':
                continue
            try:
                int(col0)
            except ValueError:
                continue
            ref_name = row[1].strip()
            ref_url = row[2].strip()
            if ref_name:
                refs[ref_name] = ref_url
    return refs


def count_agree_disagree(references_str, interaction_code):
    """
    Count how many individual source citations in the references string
    agree with the current interaction, and how many disagree.
    The references string has format like:
      "Favorise d'après 'X', Défavorise d'après 'Y', Favorise d'après 'Z'"
    Returns (n_agree, n_disagree).
    """
    if not references_str:
        return (1, 0)
    # Map interaction codes to their French labels
    agree_label = interaction_forward.get(interaction_code, '').lower()
    opposite = {'pos': 'neg', 'neg': 'pos', 'atr': 'rep', 'rep': 'atr'}
    disagree_label = interaction_forward.get(opposite.get(interaction_code, ''), '').lower()

    parts = [p.strip() for p in references_str.split(",") if "d'après" in p]
    n_agree = 0
    n_disagree = 0
    for part in parts:
        part_lower = part.lower().strip()
        if part_lower.startswith(agree_label):
            n_agree += 1
        elif disagree_label and part_lower.startswith(disagree_label):
            n_disagree += 1
    if n_agree == 0 and n_disagree == 0:
        n_agree = 1
    return (n_agree, n_disagree)


# ---------------------------------------------------------------------------
# JS generation (rewritten from app.py generate_js without DB)
# ---------------------------------------------------------------------------

def generate_data_js(species, associations_raw, has_weights=False, arrow_mode="all"):
    """
    Build the data.js content from species dict and raw association list.
    arrow_mode: "all" (arrowheads on every link), "none" (no arrowheads),
               "animals_only" (arrowheads only on links involving animals).
    Returns (js_content: str, examples: list, categories_list: list,
             cat_plants_ids: list, cat_animals_ids: list, dict_interactions: dict,
             index_to_name: dict, appartenance: dict)
    """
    # Build index mappings
    name_to_index = {}
    species_cat = {}
    species_wiki = {}
    species_ncbi = {}
    appartenance = {}

    for enum_id, name in enumerate(sorted(species.keys())):
        sp = species[name]
        name_to_index[name] = enum_id
        species_cat[name] = sp["category"]
        species_wiki[name] = sp["wiki"]
        species_ncbi[name] = sp["NCBI"]
        appartenance[enum_id] = reverse_cat.get(sp["category"], 0)

    index_to_name = reverse_dict(name_to_index)

    # Build association dict: (source_idx, target_idx) → {inter_int, refs, weight}
    # Using a dict to preserve weight/refs (unlike the old set-based approach)
    associations_dict = {}
    for source, inter_int, target, references, weight in associations_raw:
        si = name_to_index[source]
        ti = name_to_index[target]
        key = (si, ti)
        inter_code = interactions[inter_int]
        if key not in associations_dict:
            associations_dict[key] = {
                "inter_int": reverse_interactions[inter_code],
                "inter_code": inter_code,
                "refs": references,
                "weight": weight,
            }

    # Build a set view for backward compatibility with examples/legend code
    associations_plant = set()
    for (si, ti), data in associations_dict.items():
        associations_plant.add((si, ti, data["inter_int"]))

    # ---- Build JS string ----
    lines = []
    lines.append("var graph = {")

    # nodes
    lines.append('\t"nodes":[')
    node_lines = []
    for index in sorted(index_to_name.keys()):
        name = index_to_name[index]
        node_lines.append(
            '\t\t{{"name":"{0}","group":{1},"value":{2},"wiki":"{3}","ncbi":"{4}"}}'.format(
                name, appartenance[index], index, species_wiki[name], species_ncbi[name]
            )
        )
    lines.append(",\n".join(node_lines))
    lines.append("\t],")

    # forward adjacency list
    lines.append('\t"forward":[')
    fwd_lines = []
    for index in sorted(index_to_name.keys()):
        entries_list = []
        for (si, ti), data in sorted(associations_dict.items()):
            if si != index:
                continue
            inter_code = data["inter_code"]
            weight = data["weight"]
            refs = data["refs"]
            n_agree, n_disagree = count_agree_disagree(refs, inter_code) if has_weights else (1, 0)
            escaped_refs = refs.replace('\\', '\\\\').replace('"', '\\"') if has_weights else ""
            if has_weights:
                entries_list.append(
                    '{{"target":{0},"value":"{1}","group":{2},"weight":{3},"n_agree":{4},"n_disagree":{5},"refs":"{6}"}}'.format(
                        ti, inter_code, appartenance[ti], weight, n_agree, n_disagree, escaped_refs
                    )
                )
            else:
                entries_list.append(
                    '{{"target":{0},"value":"{1}","group":{2}}}'.format(
                        ti, inter_code, appartenance[ti]
                    )
                )
        fwd_lines.append("\t\t[" + ",".join(entries_list) + "]")
    lines.append(",\n".join(fwd_lines))
    lines.append("\t],")

    # backward adjacency list
    lines.append('\t"backward":[')
    bwd_lines = []
    for index in sorted(index_to_name.keys()):
        entries_list = []
        for (si, ti), data in sorted(associations_dict.items()):
            if ti != index:
                continue
            inter_code = data["inter_code"]
            weight = data["weight"]
            refs = data["refs"]
            n_agree, n_disagree = count_agree_disagree(refs, inter_code) if has_weights else (1, 0)
            escaped_refs = refs.replace('\\', '\\\\').replace('"', '\\"') if has_weights else ""
            if has_weights:
                entries_list.append(
                    '{{"source":{0},"value":"{1}","group":{2},"weight":{3},"n_agree":{4},"n_disagree":{5},"refs":"{6}"}}'.format(
                        si, inter_code, appartenance[si], weight, n_agree, n_disagree, escaped_refs
                    )
                )
            else:
                entries_list.append(
                    '{{"source":{0},"value":"{1}","group":{2}}}'.format(
                        si, inter_code, appartenance[si]
                    )
                )
        bwd_lines.append("\t\t[" + ",".join(entries_list) + "]")
    lines.append(",\n".join(bwd_lines))
    lines.append("\t]")
    lines.append("};")

    # has_weights flag
    lines.append("var has_weights = " + ("true" if has_weights else "false") + ";")

    # arrow_mode
    lines.append('var arrow_mode = "' + arrow_mode + '";')

    # names list
    lines.append('var names_liste = ["' + '","'.join(sorted(set(species_cat.values()))) + '"];')

    # groups
    lines.append("var groups = {")
    lines.append(",\n".join(['\t{0}:"{1}"'.format(ci, cn) for ci, cn in categories.items()]))
    lines.append("};")

    # color
    lines.append("var color = {")
    lines.append(",\n".join(['\t{0}:"{1}"'.format(ci, cn) for ci, cn in color.items()]))
    lines.append("};")

    # category arrays
    lines.append("var cat_animals = [" + ",".join(sorted(str(reverse_cat[c]) for c in cat_animals)) + "];")
    lines.append("var cat_pests = [" + ",".join(sorted(str(reverse_cat[c]) for c in cat_pests)) + "];")
    lines.append("var cat_helpers = [" + ",".join(sorted(str(reverse_cat[c]) for c in (cat_animals - cat_pests))) + "];")
    lines.append("var cat_plants = [" + ",".join(sorted(str(reverse_cat[c]) for c in cat_plants)) + "];")

    # interactions
    lines.append('var interactions = ["' + '","'.join(sorted(set(interactions.values()))) + '"];')
    backward = ", ".join(
        ['"{0}":"{1}"'.format(v, interaction_backward[v].lower()) for v in sorted(set(interactions.values()))]
    )
    forward = ", ".join(
        ['"{0}":"{1}"'.format(v, interaction_forward[v].lower()) for v in sorted(set(interactions.values()))]
    )
    lines.append('var filter_name_dico = {"backward":{' + backward + '}, "forward":{' + forward + '}};')

    js_content = "\n".join(lines)

    # ---- Build examples for legend ----
    examples = []
    for index in sorted(index_to_name.keys()):
        name = index_to_name[index]
        name_associations = [a for a in associations_plant if a[0] == index]
        name_interactions = set(a[2] for a in name_associations)
        if len(name_interactions) == len(description_interactions):
            for interaction_val in sorted(name_interactions, key=lambda x: abs(x)):
                matched = [a for a in name_associations if a[2] == interaction_val]
                source_idx, target_idx, inter = matched[0]
                example = {
                    "name_source": index_to_name[source_idx],
                    "color_source": color[appartenance[source_idx]],
                    "name_target": index_to_name[target_idx],
                    "color_target": color[appartenance[target_idx]],
                    "link": interactions[inter],
                    "description": "{0} {1} {2}".format(
                        index_to_name[source_idx],
                        interaction_forward[interactions[inter]].lower(),
                        index_to_name[target_idx].lower(),
                    ),
                }
                examples.append(example)
            break

    # categories list for legend
    categories_list = []
    for cat_set in [sorted(cat_plants), sorted(cat_animals)]:
        categories_list += [(k, color[reverse_cat[k]]) for k in cat_set]

    cat_plants_ids = sorted(reverse_cat[c] for c in cat_plants)
    cat_animals_ids = sorted(reverse_cat[c] for c in cat_animals)
    dict_interactions = {"backward": interaction_backward, "forward": interaction_forward}

    return (js_content, examples, categories_list, cat_plants_ids, cat_animals_ids,
            dict_interactions, index_to_name, appartenance)


# ---------------------------------------------------------------------------
# Asset compilation & copying
# ---------------------------------------------------------------------------

def copy_vendor_assets():
    """Copy vendor assets from templates/ to static/."""
    os.makedirs(os.path.join(STATIC_DIR, "css"), exist_ok=True)
    os.makedirs(os.path.join(STATIC_DIR, "js"), exist_ok=True)
    os.makedirs(os.path.join(STATIC_DIR, "fonts"), exist_ok=True)

    # CSS
    shutil.copy2(os.path.join(TEMPLATES_DIR, "css", "bootstrap.min.css"),
                 os.path.join(STATIC_DIR, "css", "bootstrap.min.css"))

    # JS vendor files
    for name in ["jquery-3.1.1.min.js", "bootstrap.min.js", "d3.min.js",
                 "jets.min.js", "jquery.scrollTo.min.js", "cookie.min.js"]:
        shutil.copy2(os.path.join(TEMPLATES_DIR, "js", name),
                     os.path.join(STATIC_DIR, "js", name))

    # Fonts
    for f in os.listdir(os.path.join(TEMPLATES_DIR, "fonts")):
        shutil.copy2(os.path.join(TEMPLATES_DIR, "fonts", f),
                     os.path.join(STATIC_DIR, "fonts", f))

    # Favicon
    favicon_src = os.path.join(TEMPLATES_DIR, "favicon.ico")
    if os.path.exists(favicon_src):
        shutil.copy2(favicon_src, os.path.join(STATIC_DIR, "favicon.ico"))

    print(OKBLUE + "Vendor assets copied to static/" + ENDC)


def compile_scss():
    """Compile SCSS to minified CSS."""
    scss_path = os.path.join(TEMPLATES_DIR, "MonPotager.css.scss")
    css_out = os.path.join(STATIC_DIR, "css", "MonPotager.min.css")
    compiled = sass.compile(filename=scss_path, output_style="compressed")
    with open(css_out, "w") as f:
        f.write(compiled)
    print(OKBLUE + "Compiled SCSS → static/css/MonPotager.min.css" + ENDC)


def minify_js():
    """Minify the main MonPotager.js file."""
    src = os.path.join(TEMPLATES_DIR, "js", "MonPotager.js")
    dst = os.path.join(STATIC_DIR, "js", "MonPotager.min.js")
    with open(src, "r") as f:
        content = f.read()
    with open(dst, "w") as f:
        f.write(jsmin(content))
    print(OKBLUE + "Minified MonPotager.js → static/js/MonPotager.min.js" + ENDC)


def write_data_js(js_content, output_name):
    """Write and minify a data JS file."""
    raw_path = os.path.join(STATIC_DIR, "js", output_name.replace(".min.js", ".js"))
    min_path = os.path.join(STATIC_DIR, "js", output_name)
    with open(raw_path, "w") as f:
        f.write(js_content)
    with open(min_path, "w") as f:
        f.write(jsmin(js_content))
    print(OKBLUE + f"Generated static/js/{output_name}" + ENDC)


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def render_html(output_filename, data_js_name, version_label,
                datasets,
                examples, categories_list, cat_plants_ids, cat_animals_ids,
                dict_interactions, index_to_name, appartenance):
    """Render the Jinja2 template to an HTML file."""
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(ROOT_DIR))
    template = env.get_template("templates/MonPotager.html")

    plants = index_to_name
    first_letter = sorted(set(
        name[0].upper() for key, name in plants.items()
        if appartenance[key] in cat_plants_ids
    ))
    sorted_appartenance = sorted(appartenance.items(), key=lambda pl: plants[pl[0]].lower())

    output_path = os.path.join(ROOT_DIR, output_filename)
    template.stream(
        timestamp=datetime.now().timestamp(),
        months={name: [] for name in plants.values()},
        plants=plants,
        examples=examples,
        data_js_name=data_js_name,
        cat_plants=cat_plants_ids,
        cat_animals=cat_animals_ids,
        categories=categories_list,
        first_letter=first_letter,
        interactions=dict_interactions,
        appartenance=sorted_appartenance,
        version_label=version_label,
        datasets=datasets,
        current_url=output_filename,
    ).dump(output_path)

    print(OKGREEN + f"Generated {output_filename}" + ENDC)


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

def build():
    print("=" * 60)
    print("MonPotager Static Site Generator")
    print("=" * 60)

    # 1. Copy vendor assets
    copy_vendor_assets()

    # 2. Compile SCSS
    compile_scss()

    # 3. Minify MonPotager.js
    minify_js()

    # 4. Load all three datasets
    # --- Paut ---
    print("\n--- Paut version (index.html) ---")
    paut_species = read_species_csv(os.path.join(DATA_DIR, "paut_formatted_especes.csv"))
    paut_assocs = read_associations_csv(os.path.join(DATA_DIR, "paut_formatted_associations.csv"), paut_species)
    paut_species = filter_species_with_associations(paut_species, paut_assocs)
    print(f"Paut: {len(paut_species)} species, {len(paut_assocs)} associations")

    ref_map = read_references_csv(os.path.join(DATA_DIR, "paut_references.csv"))
    print(f"Paut references: {len(ref_map)} entries")

    (paut_js, paut_examples, paut_cats, paut_plant_ids, paut_animal_ids,
     paut_dict_inter, paut_idx2name, paut_appart) = generate_data_js(
        paut_species, paut_assocs, has_weights=True, arrow_mode="none")
    paut_js += "\nvar references = " + json.dumps(ref_map, ensure_ascii=False) + ";\n"
    write_data_js(paut_js, "data_paut.min.js")

    # --- Original ---
    print("\n--- Original version (MonPotager.html) ---")
    orig_species = read_species_csv(os.path.join(DATA_DIR, "especes_v2.csv"))
    orig_assocs = read_associations_csv(os.path.join(DATA_DIR, "associations.csv"), orig_species)
    orig_species = filter_species_with_associations(orig_species, orig_assocs)
    print(f"Original: {len(orig_species)} species, {len(orig_assocs)} associations")

    (orig_js, orig_examples, orig_cats, orig_plant_ids, orig_animal_ids,
     orig_dict_inter, orig_idx2name, orig_appart) = generate_data_js(
        orig_species, orig_assocs, has_weights=False, arrow_mode="all")
    write_data_js(orig_js, "data_original.min.js")

    # --- Merged ---
    print("\n--- Merged version (merged.html) ---")
    merged_species = read_species_csv(os.path.join(DATA_DIR, "merged_especes.csv"))
    merged_assocs = read_associations_csv(os.path.join(DATA_DIR, "merged_associations.csv"), merged_species)
    merged_species = filter_species_with_associations(merged_species, merged_assocs)
    print(f"Merged: {len(merged_species)} species, {len(merged_assocs)} associations")

    (merged_js, merged_examples, merged_cats, merged_plant_ids, merged_animal_ids,
     merged_dict_inter, merged_idx2name, merged_appart) = generate_data_js(
        merged_species, merged_assocs, has_weights=True, arrow_mode="animals_only")
    merged_js += "\nvar references = " + json.dumps(ref_map, ensure_ascii=False) + ";\n"
    write_data_js(merged_js, "data_merged.min.js")

    # 5. Build datasets list for template
    datasets = [
        {"label": "Associations entre plantes", "url": "index.html",
         "n_species": len(paut_species), "n_assoc": len(paut_assocs),
         "description": "Uniquement les associations entre plantes, issues du projet Paut et\u00a0al."},
        {"label": "Inclure les nuisibles", "url": "MonPotager.html",
         "n_species": len(orig_species), "n_assoc": len(orig_assocs),
         "description": "Inclut les nuisibles et auxiliaires, à partir de deux ouvrages de référence."},
        {"label": "Données fusionnées", "url": "merged.html",
         "n_species": len(merged_species), "n_assoc": len(merged_assocs),
         "description": "Fusion des deux sources de données ci-dessus."},
    ]

    # 6. Render all three HTML pages
    render_html(
        output_filename="index.html",
        data_js_name="data_paut",
        version_label="Paut",
        datasets=datasets,
        examples=paut_examples,
        categories_list=paut_cats,
        cat_plants_ids=paut_plant_ids,
        cat_animals_ids=paut_animal_ids,
        dict_interactions=paut_dict_inter,
        index_to_name=paut_idx2name,
        appartenance=paut_appart,
    )
    render_html(
        output_filename="MonPotager.html",
        data_js_name="data_original",
        version_label="Originale",
        datasets=datasets,
        examples=orig_examples,
        categories_list=orig_cats,
        cat_plants_ids=orig_plant_ids,
        cat_animals_ids=orig_animal_ids,
        dict_interactions=orig_dict_inter,
        index_to_name=orig_idx2name,
        appartenance=orig_appart,
    )
    render_html(
        output_filename="merged.html",
        data_js_name="data_merged",
        version_label="Fusionnée",
        datasets=datasets,
        examples=merged_examples,
        categories_list=merged_cats,
        cat_plants_ids=merged_plant_ids,
        cat_animals_ids=merged_animal_ids,
        dict_interactions=merged_dict_inter,
        index_to_name=merged_idx2name,
        appartenance=merged_appart,
    )

    print("\n" + OKGREEN + "Build complete!" + ENDC)
    print(f"Serve locally: python -m http.server 8000")
    print(f"Then open http://localhost:8000/")


if __name__ == "__main__":
    build()
