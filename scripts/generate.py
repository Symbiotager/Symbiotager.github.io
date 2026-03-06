#!/usr/bin/env python3
"""
Static site generator for MonPotager.
Reads CSV data files and Jinja2 templates, produces two HTML versions:
  - index.html       (Paut data, default)
  - MonPotager.html   (Original Google Sheets data)
along with their respective data JS files and shared static assets.
"""

import csv
import os
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
    Read an associations CSV file and return a list of (source, interaction_str, target) tuples.
    Only includes associations where both source and target exist in valid_species.
    Handles both paut_formatted and original formats (both have source, interaction, target in cols 0-2).
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
            assocs.append((source, inter_int, target))
    return assocs


# ---------------------------------------------------------------------------
# JS generation (rewritten from app.py generate_js without DB)
# ---------------------------------------------------------------------------

def generate_data_js(species, associations_raw):
    """
    Build the data.js content from species dict and raw association list.
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

    # Build unique association tuples (source_index, target_index, interaction_int)
    associations_plant = set()
    for source, inter_int, target in associations_raw:
        si = name_to_index[source]
        ti = name_to_index[target]
        associations_plant.add((si, ti, reverse_interactions[interactions[inter_int]]))

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
        entries = ",".join(
            '{{"target":{0},"value":"{1}","group":{2}}}'.format(
                target, interactions[inter], appartenance[target]
            )
            for source, target, inter in associations_plant if source == index
        )
        fwd_lines.append("\t\t[" + entries + "]")
    lines.append(",\n".join(fwd_lines))
    lines.append("\t],")

    # backward adjacency list
    lines.append('\t"backward":[')
    bwd_lines = []
    for index in sorted(index_to_name.keys()):
        entries = ",".join(
            '{{"source":{0},"value":"{1}","group":{2}}}'.format(
                source, interactions[inter], appartenance[source]
            )
            for source, target, inter in associations_plant if target == index
        )
        bwd_lines.append("\t\t[" + entries + "]")
    lines.append(",\n".join(bwd_lines))
    lines.append("\t]")
    lines.append("};")

    # names list
    lines.append('var names_liste = ["' + '","'.join(sorted(set(species_cat))) + '"];')

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
                other_url, other_label,
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
        other_version_url=other_url,
        other_version_label=other_label,
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

    # 4. Paut version (default → index.html)
    print("\n--- Paut version (index.html) ---")
    paut_species = read_species_csv(os.path.join(DATA_DIR, "paut_formatted_especes.csv"))
    paut_assocs = read_associations_csv(os.path.join(DATA_DIR, "paut_formatted_associations.csv"), paut_species)
    print(f"Paut: {len(paut_species)} species, {len(paut_assocs)} associations")

    (paut_js, paut_examples, paut_cats, paut_plant_ids, paut_animal_ids,
     paut_dict_inter, paut_idx2name, paut_appart) = generate_data_js(paut_species, paut_assocs)
    write_data_js(paut_js, "data_paut.min.js")
    render_html(
        output_filename="index.html",
        data_js_name="data_paut",
        version_label="Paut",
        other_url="MonPotager.html",
        other_label="Version originale",
        examples=paut_examples,
        categories_list=paut_cats,
        cat_plants_ids=paut_plant_ids,
        cat_animals_ids=paut_animal_ids,
        dict_interactions=paut_dict_inter,
        index_to_name=paut_idx2name,
        appartenance=paut_appart,
    )

    # 5. Original version (→ MonPotager.html)
    print("\n--- Original version (MonPotager.html) ---")
    orig_species = read_species_csv(os.path.join(DATA_DIR, "especes_v2.csv"))
    orig_assocs = read_associations_csv(os.path.join(DATA_DIR, "associations.csv"), orig_species)
    print(f"Original: {len(orig_species)} species, {len(orig_assocs)} associations")

    (orig_js, orig_examples, orig_cats, orig_plant_ids, orig_animal_ids,
     orig_dict_inter, orig_idx2name, orig_appart) = generate_data_js(orig_species, orig_assocs)
    write_data_js(orig_js, "data_original.min.js")
    render_html(
        output_filename="MonPotager.html",
        data_js_name="data_original",
        version_label="Originale",
        other_url="index.html",
        other_label="Version Paut (par défaut)",
        examples=orig_examples,
        categories_list=orig_cats,
        cat_plants_ids=orig_plant_ids,
        cat_animals_ids=orig_animal_ids,
        dict_interactions=orig_dict_inter,
        index_to_name=orig_idx2name,
        appartenance=orig_appart,
    )

    print("\n" + OKGREEN + "Build complete!" + ENDC)
    print(f"Serve locally: python -m http.server 8000")
    print(f"Then open http://localhost:8000/")


if __name__ == "__main__":
    build()
