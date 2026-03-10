import wikipedia
from Bio import Entrez
import requests
from bs4 import BeautifulSoup


def find_latin_name(nom_fr):
    """
    Fonction permettant à partir d'un nom commun d'espèce en français de ressortir un dictionnaire avec pour clé le nom commun et comme valeurs:
    - le nom commun français
    - le lien wikipedia de ce nom commun
    - son rang taxonomique
    - le nom latin
    """
    print(f"Recherche du nom latin pour l'espèce: {nom_fr}")
    global u
    dico_fr = dict()
    wikipedia.set_lang("fr")
    key = nom_fr

    expected_names = {"mil": "millet"}
    try:
        # Normal search flow
        search = wikipedia.search(expected_names.get(nom_fr, nom_fr))
        if search == list():
            taxon = "taxon non trouvé"
            nom_latin = "nom latin non trouvé"
            url = "https://fr.wikipedia.org/"
            dico_fr[key] = [key, url, taxon, nom_latin]
            return dico_fr

        search = search[0]
        wiki = wikipedia.WikipediaPage(search)
        url = wiki.url
    except wikipedia.exceptions.DisambiguationError as e:
        # Handle disambiguation
        # Try to find a good option from the disambiguation list
        plant_related_terms = ["céréale", "plante", "grain", "culture", "agriculture"]
        potential_options = []

        # First pass: look for options containing plant-related terms
        for option in e.options:
            option_lower = option.lower()
            if any(term in option_lower for term in plant_related_terms):
                potential_options.append(option)

        # If no plant-related options found, use longer options (less likely to be disambiguation pages)
        if not potential_options:
            potential_options = [opt for opt in e.options if len(opt) > 3 and opt.lower() != nom_fr.lower()][:5]

        # If still no options, use the first option
        if not potential_options and e.options:
            potential_options = [e.options[0]]

        # Try each potential option until one works
        for option in potential_options:
            try:
                wiki = wikipedia.WikipediaPage(option)
                url = wiki.url
                dico_fr[key] = [key, url, "taxon from disambiguation", option]
                return dico_fr
            except Exception:
                continue

        # If all else fails, return a default response
        taxon = "taxon non trouvé"
        nom_latin = "nom latin non trouvé"
        url = "https://fr.wikipedia.org/"
        dico_fr[key] = [key, url, taxon, nom_latin]
        return dico_fr

    requete = requests.get(url)
    page = requete.content
    soup = BeautifulSoup(page, features="lxml")
    if soup.find("div", {"class": "center taxobox_classification"}) is None:
        nom_latin = "nom latin non trouvé"
    else:
        nom_latin = soup.find("div", {"class": "center taxobox_classification"}).text
    for count, i in enumerate(nom_latin):
        u = int()
        if count == 0:
            continue
        elif i == " ":
            continue
        elif i == "'":
            continue
        elif i == ".":
            continue
        elif i.upper() == i:
            u = count
            break
        else:
            u = 20
    nom_latin = nom_latin[:u]
    if soup.find("p", {"class": "bloc"}) is None:
        taxon = "taxon non trouvé"
    else:
        taxon = soup.find("p", {"class": "bloc"}).text

    # création du dictionnaire de sortie
    dico_fr[key] = [key, url, taxon, nom_latin]
    return dico_fr


def find_tax_id(dico_fr):
    """
    Cette fonction prend en entré un dictionnaire ayant pour clé le nom commmun français et comme valeur:
    le nom commun français, le lien wikipedia, le rang taxonomique et le nom latin.

    Cette fonction rajoute  à la fin des valeurs le taxID qui a été trouvé en consultant l'API du NCBI.
    """
    dico = dict()
    for key, value in dico_fr.items():
        value = list(value)
        Entrez.email = "thibault.latrille@gmail.com"  # Always tell NCBI who you are
        if value[3] == "nom latin non trouvé":
            value.append("")
            dico[key] = value
            return dico
        handle = Entrez.esearch(db="taxonomy", term=value[3])
        record = Entrez.read(handle)
        if len(record["IdList"]) == 0:
            value.append(" ")
            dico[key] = value
            return dico
        taxID = record["IdList"][0]
        taxID = str(taxID)
        value.append(taxID)
        dico[key] = value
    return dico


def enrich_species_db(species_db, clean_string):
    """Enrich species with Wikipedia and NCBI taxonomy data for species missing wiki info."""
    to_enrich = [name for name, sp in species_db.items() if not sp.get('wiki')]
    print(f"Enriching {len(to_enrich)} species with Wikipedia/NCBI data...")
    latin_placeholder = {'nom latin non trouvé', 'nom latin non trouve', ''}
    for name in to_enrich:
        sp = species_db[name]
        try:
            dico = find_latin_name(name)
            value = list(dico.get(name, []))
            if len(value) < 4:
                continue
            # Prefer existing latin name for NCBI taxonomy search
            if sp['latin_name'] and sp['latin_name'] not in latin_placeholder:
                value[3] = sp['latin_name']
            dico = find_tax_id({name: value})
            value = dico.get(name, [])
            if not value:
                continue
            # Update wiki URL
            if len(value) > 1 and value[1] and value[1] != 'https://fr.wikipedia.org/':
                sp['wiki'] = clean_string(value[1])
            # Update taxonomy if currently empty
            if not sp['taxonomy'] and len(value) > 2 and value[2] and value[2] not in ('taxon non trouvé',
                                                                                       'taxon from disambiguation'):
                sp['taxonomy'] = clean_string(value[2])
            # Update latin_name if currently empty or placeholder
            if (not sp['latin_name'] or sp['latin_name'] in latin_placeholder) and len(value) > 3 and value[3] and \
                    value[3] not in latin_placeholder:
                sp['latin_name'] = clean_string(value[3])
            # Update TaxID and NCBI URL
            if len(value) >= 5 and value[4] and str(value[4]).strip():
                tax_id = str(value[4]).strip()
                sp['TaxID'] = tax_id
                sp['NCBI'] = f"https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id={tax_id}"
        except Exception as e:
            print(f"  Warning: enrichment failed for '{name}': {e}")
    print("Enrichment complete.")
