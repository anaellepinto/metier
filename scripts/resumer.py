r"""Lit les offres actives du jour (data/actives/<date>.csv), retrouve leur dernière version dans
data/brut, et écrit data/resume.json : le fichier que la page index.html affiche.

Usage :
    .venv\Scripts\python.exe scripts\resumer.py

C'est ici que la donnée brute est retravaillée :
  - salaire : libellé texte -> minimum et maximum annuels bruts ;
  - outils cités dans l'intitulé + la description (grille OUTILS, à adapter à votre métier) ;
  - position sur la carte : latitude/longitude de l'API quand elle les donne, sinon le centre
    de la commune (geo.api.gouv.fr, mis en cache dans data/geo/), sinon la ville principale
    du département ; les offres « France » n'ont pas de point.
  - niveau de poste déduit de l'intitulé (assistant / chargé / responsable / directeur / autre),
    nature du contrat (apprentissage, professionnalisation, salarié, non salarié) et libellés
    lisibles des codes de contrat (clé « contrats » du résumé).
  - stage : l'API n'a pas de type de contrat « stage » ; une offre est un stage quand son
    intitulé le dit (est_stage). La page la range alors sous le libellé unique « Stage ».
  - source : chaque offre porte sa source (France Travail, La bonne alternance, Adzuna, Jooble)
    et, si l'annonce vient d'un site partenaire de France Travail, le nom de ce partenaire ;
    dedoublonner() retire les doublons entre sources (même employeur, intitulé proche, même
    département), en gardant la source la plus prioritaire (ordre de SOURCES).
    Les offres des autres sources sont lues dans data/autres/ (scripts/autres_sources.py).
  - exigences : exp_exige, exp_ans (années, 0 = débutant accepté), qualification, formation
    (niveau le plus élevé demandé), secteur, temps (plein/partiel), postes.
La page recalcule ensuite tous les comptages côté navigateur, selon les métiers cochés.
"""
import csv
import json
import re
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

import requests

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "scripts"))
from extraire import METIERS, ONGLETS  # noqa: E402  (la liste des métiers vit dans un seul fichier)
import autres_sources  # noqa: E402  (La bonne alternance, Adzuna, Jooble : data/autres/)

# Les outils et compétences que l'on cherche dans les annonces : c'est VOTRE grille, adaptez-la.
# Chaque entrée : libellé affiché -> variantes cherchées (mot entier, insensible à la casse).
OUTILS = {
    "SEO": ["seo", "référencement naturel"],
    "SEA / Google Ads": ["sea", "google ads", "adwords"],
    "Meta Ads": ["meta ads", "facebook ads", "instagram ads"],
    "Google Analytics": ["google analytics", "ga4", "analytics"],
    "HubSpot": ["hubspot"],
    "CRM / Salesforce": ["crm", "salesforce"],
    "Emailing": ["emailing", "e-mailing", "newsletter", "mailchimp", "brevo", "sendinblue"],
    "Réseaux sociaux": ["réseaux sociaux", "social media", "community management"],
    "LinkedIn": ["linkedin"],
    "WordPress": ["wordpress"],
    "Shopify / e-commerce": ["shopify", "prestashop", "e-commerce", "ecommerce"],
    "Canva": ["canva"],
    "Suite Adobe": ["photoshop", "illustrator", "indesign", "adobe"],
    "Excel": ["excel"],
    "Power BI / Looker": ["power bi", "looker", "data studio"],
    "SQL / Python": ["sql", "python"],
    "Marketing automation": ["automation", "automatisation", "zapier", "make", "n8n"],
    "IA générative": ["ia", "intelligence artificielle", "chatgpt", "ia générative", "genai", "llm"],
    "Anglais": ["anglais", "english"],
}
REGEX_OUTILS = {nom: re.compile(r"(?<![\w-])(" + "|".join(re.escape(v) for v in variantes) + r")(?![\w-])")
                for nom, variantes in OUTILS.items()}

GEO = "https://geo.api.gouv.fr"

# Niveau du poste, lu dans l'intitulé : l'ordre compte (un « directeur marketing » n'est pas
# un « chargé »). Première expression qui correspond, en minuscules.
NIVEAUX = [
    ("directeur", r"directeur|directrice|\bhead of\b|\bcdo\b|\bcmo\b|\bvp\b"),
    ("responsable", r"responsable|manager|\bchef|\bcheffe|\blead\b|\bhead\b"),
    ("assistant", r"assistant|alternan|apprenti|stagiaire|\bstage\b|junior"),
    ("charge", r"charg[ée]|consultant|analyste|analyst|spécialiste|specialist|traffic|community"
                r"|expert|technicien|conseiller|animateur|référenceur|rédacteur|designer"
                r"|développeur|business developer|ingénieur|gestionnaire|coordinateur|superviseur"),
]
REGEX_NIVEAUX = [(cle, re.compile(motif, re.IGNORECASE)) for cle, motif in NIVEAUX]
NIVEAUX_LIBELLES = [
    ["assistant", "Assistant·e / junior"],
    ["charge", "Chargé·e"],
    ["responsable", "Responsable"],
    ["directeur", "Directeur·rice"],
    ["autre", "Autre"],
]

# Codes de type de contrat de l'API -> libellé court lisible par un étudiant.
CONTRATS = {
    "CDI": "CDI",
    "CDD": "CDD",
    "MIS": "Intérim",
    "SAI": "Saisonnier",
    "FRA": "Franchise",
    "LIB": "Profession libérale",
    "CCE": "Profession commerciale",
    "DDI": "CDI de chantier",
    "DIN": "CDI intérimaire",
    "TTI": "Intérim",
    "CDS": "CDD senior",
    "REP": "Reprise d'entreprise",
}

NATURES = [
    ("apprentissage", "apprentissage"),
    ("professionnalisation", "professionnalisation"),
    ("non salarié", "non_salarie"),
    ("contrat travail", "salarie"),
]

# Stage : « Stage », « Stagiaire », « STAGE - … » dans l'intitulé. « Alternance ou stage » reste
# une alternance quand France Travail l'a codée en apprentissage ou professionnalisation.
MOTIF_STAGE = re.compile(r"\bstag(e|iaire|iaires)\b", re.IGNORECASE)
MOTIF_ALTERNANCE = re.compile(r"alternan|apprenti|contrat pro", re.IGNORECASE)

SOURCE_FT = "France Travail"
# Ordre d'affichage et de priorité : en cas de doublon, l'offre de la première source est gardée.
# France Travail d'abord (c'est la veille de référence), puis le service public, puis les agrégateurs.
SOURCES = [SOURCE_FT, "La bonne alternance", "Adzuna", "Jooble"]

# Niveau de formation demandé : du plus faible au plus élevé (l'ordre sert aussi à l'affichage).
FORMATIONS = ["< Bac", "Bac", "Bac+2", "Bac+3/4", "Bac+5"]


def niveau(intitule):
    """'Directeur marketing' -> 'directeur' ; 'Chargé de com' -> 'charge' ; sinon 'autre'."""
    t = intitule or ""
    for cle, rx in REGEX_NIVEAUX:
        if rx.search(t):
            return cle
    return "autre"


def contrat_libelle(code):
    """Code de contrat de l'API -> libellé court ; les codes inconnus restent identifiables."""
    return CONTRATS.get(code) or f"Autre ({code})"


def nature(o):
    """natureContrat -> 'apprentissage' | 'professionnalisation' | 'salarie' | 'non_salarie' | 'autre'."""
    lib = (o.get("natureContrat") or "").lower()
    if not lib:
        return "autre"
    for motif, cle in NATURES:
        if motif in lib:
            return cle
    return "autre"


def est_stage(o):
    """True si l'intitulé annonce un stage, sauf alternance déclarée comme telle."""
    return stage_intitule(o.get("intitule"), nature(o))


def stage_intitule(intitule, nat):
    """« Stage - Assistant marketing » -> True ; « Alternance ou stage » codée en apprentissage -> False."""
    t = intitule or ""
    if not MOTIF_STAGE.search(t):
        return False
    return not (MOTIF_ALTERNANCE.search(t) and nat in ("apprentissage", "professionnalisation"))


def partenaire(o):
    """Le site partenaire d'où France Travail a repris l'annonce (« PMEJOB »…), sinon None."""
    ps = (o.get("origineOffre") or {}).get("partenaires") or []
    return ps[0].get("nom") if ps and ps[0].get("nom") else None


def cle_doublon(o):
    """Même employeur + même intitulé (hors H/F, ponctuation, accents) + même département."""
    def norme(t):
        t = unicodedata.normalize("NFKD", (t or "").lower())
        t = "".join(c for c in t if not unicodedata.combining(c))
        t = re.sub(r"\((h|f)\s*/\s*(h|f)(\s*/\s*x)?\)|\b(h|f)\s*/\s*(h|f)\b", " ", t)
        return " ".join(re.findall(r"[a-z0-9]+", t))
    ent = norme(o.get("entreprise"))
    return (ent, norme(o.get("intitule")), o.get("dep") or "") if ent else None


def dedoublonner(offres):
    """Retire d'une source les offres déjà publiées par une autre (ordre de priorité : SOURCES).
    Les doublons internes à une même source ne sont pas touchés : ce sont parfois de vrais postes
    multiples, et la veille France Travail les a toujours comptés."""
    rang = {s: i for i, s in enumerate(SOURCES)}
    ordre = sorted(offres, key=lambda o: rang.get(o["source"], len(SOURCES)))
    vues, gardees = {}, []
    for o in ordre:
        k = cle_doublon(o)
        if k and k in vues and vues[k] != o["source"]:
            continue
        if k:
            vues.setdefault(k, o["source"])
        gardees.append(o)
    return gardees


def exp_ans(lib):
    """'Débutant accepté'/'0 An(s)' -> 0, '6 Mois' -> 0.5, '5 An(s)' -> 5, 'Expérience exigée' -> None."""
    l = (lib or "").lower()
    if not l:
        return None
    if "débutant" in l or "debutant" in l:
        return 0
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(an|mois)", l)
    if not m:
        return None
    n = float(m.group(1).replace(",", "."))
    n = n if m.group(2) == "an" else n / 12
    return int(n) if n == int(n) else round(n, 2)


def formation(o):
    """Niveau de formation le plus élevé demandé par l'offre, ou None si rien n'est indiqué."""
    meilleur = None
    for f in o.get("formations") or []:
        l = (f.get("niveauLibelle") or "").lower()
        if not l:
            continue
        if "bac+5" in l or "bac + 5" in l:
            n = "Bac+5"
        elif "bac+3" in l or "bac+4" in l or "bac + 3" in l or "bac + 4" in l:
            n = "Bac+3/4"
        elif "bac+2" in l or "bac + 2" in l:
            n = "Bac+2"
        elif "bac" in l:
            n = "Bac"
        else:
            n = "< Bac"
        if meilleur is None or FORMATIONS.index(n) > FORMATIONS.index(meilleur):
            meilleur = n
    return meilleur


def temps_travail(o):
    """'Temps plein' -> 'plein', 'Temps partiel' -> 'partiel', sinon None."""
    l = (o.get("dureeTravailLibelleConverti") or "").lower()
    return "plein" if "plein" in l else ("partiel" if "partiel" in l else None)


# En-tête normalisé des libellés de salaire de France Travail :
# « Annuel de 32000.0 Euros à 38000.0 Euros », « Mensuel de 486.0 Euros sur 12 mois »,
# « Horaire de 12.31 Euros - 13ème mois + primes »…
MOTIF_SALAIRE = re.compile(
    r"^(annuel|mensuel|horaire)\s+de\s+(\d+(?:[.,]\d+)?)\s*euros"
    r"(?:\s*à\s*(\d+(?:[.,]\d+)?)\s*euros)?",
    re.IGNORECASE,
)
MULTIPLICATEUR = {"annuel": 1, "mensuel": 12, "horaire": 1607}
# Fenêtre de vraisemblance, en brut annuel. En dessous : l'employeur a saisi des
# milliers d'euros dans la case « annuel » (« Annuel de 32.0 Euros à 38.0 Euros »).
# Au dessus : il a saisi un salaire annuel dans la case « mensuel ». Le plancher
# laisse passer les apprentis (27 % du SMIC = 5 832 € par an).
SALAIRE_MIN, SALAIRE_MAX = 4000, 250000


def salaire_min_max(lib):
    """'Annuel de 32000.0 Euros à 38000.0 Euros' -> (32000, 38000) ; mensuel x12, horaire x1607.

    On ne lit que cet en-tête : le commentaire libre qui suit un « - » répète ou
    brouille les chiffres (« De 30 à 35 k€ par an », « 13ème mois », « 35h hebdo »),
    et « sur 12 mois » n'est pas un montant. Lire tous les nombres du libellé
    obligeait à écarter les petites valeurs, ce qui effaçait les vrais salaires
    d'apprenti (486 €/mois = 27 % du SMIC).
    """
    if not lib:
        return None, None
    m = MOTIF_SALAIRE.match(lib.strip())
    if not m:
        return None, None
    mult = MULTIPLICATEUR[m.group(1).lower()]
    vals = [float(x.replace(",", ".")) * mult for x in (m.group(2), m.group(3)) if x]
    vals = [v for v in vals if SALAIRE_MIN <= v <= SALAIRE_MAX]
    return (round(min(vals)), round(max(vals))) if vals else (None, None)


def departement(lieu):
    cp = lieu.get("codePostal") or ""
    if cp[:2].isdigit() and cp != "99999":
        return "2A" if cp[:2] == "20" and cp < "20200" else ("2B" if cp[:2] == "20" else cp[:2])
    m = re.match(r"\s*(\d{2}|2A|2B)\s*-", lieu.get("libelle") or "")
    return m.group(1) if m else ""


def sans_accents(t):
    """'Île-de-France' -> 'ile de france' : pour comparer deux noms de lieu."""
    t = unicodedata.normalize("NFKD", (t or "").lower())
    return " ".join(re.findall(r"[a-z0-9]+", "".join(c for c in t if not unicodedata.combining(c))))


# Les régions : jamais un nom de ville, à ne pas chercher comme tel.
REGIONS = {sans_accents(r) for r in (
    "Auvergne-Rhône-Alpes", "Bourgogne-Franche-Comté", "Bretagne", "Centre-Val de Loire", "Corse", "Grand Est",
    "Hauts-de-France", "Île-de-France", "Normandie", "Nouvelle-Aquitaine", "Occitanie", "Pays de la Loire",
    "Provence-Alpes-Côte d'Azur", "Guadeloupe", "Martinique", "Guyane", "La Réunion", "Mayotte")}


class Geocodeur:
    """Centre des communes et villes principales des départements, via geo.api.gouv.fr, avec cache."""

    def __init__(self):
        self.dossier = RACINE / "data" / "geo"
        self.dossier.mkdir(parents=True, exist_ok=True)
        self.communes = self._lire("communes.json")
        self.departements = self._lire("departements.json")
        self.noms = self._lire("noms.json")
        self.appels = 0

    def _lire(self, nom):
        f = self.dossier / nom
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}

    def _get(self, url):
        self.appels += 1
        time.sleep(0.05)
        try:
            r = requests.get(url, timeout=15)
            return r.json() if r.status_code == 200 else None
        except requests.RequestException:
            return None

    def commune(self, code):
        if code not in self.communes:
            d = self._get(f"{GEO}/communes/{code}?fields=centre")
            self.communes[code] = d["centre"]["coordinates"][::-1] if d and d.get("centre") else None
        return self.communes[code]

    def departement(self, code):
        if code not in self.departements:
            d = self._get(f"{GEO}/communes?codeDepartement={code}&fields=centre&boost=population&limit=1")
            self.departements[code] = d[0]["centre"]["coordinates"][::-1] if d else None
        return self.departements[code]

    def position(self, lieu):
        """(lat, lon, précision) ; précision = 'offre', 'commune', 'departement' ou None."""
        if lieu.get("latitude") and lieu.get("longitude"):
            return lieu["latitude"], lieu["longitude"], "offre"
        if lieu.get("commune"):
            p = self.commune(lieu["commune"])
            if p:
                return p[0], p[1], "commune"
        dep = departement(lieu)
        if dep:
            p = self.departement(dep)
            if p:
                return p[0], p[1], "departement"
        return None, None, None

    def ville(self, nom):
        """'Clermont-Ferrand' -> [lat, lon, département] de la commune la plus peuplée de ce nom."""
        cle = nom.strip().lower()
        if cle not in self.noms:
            d = self._get(f"{GEO}/communes?nom={requests.utils.quote(nom)}&fields=centre,codeDepartement"
                          f"&boost=population&limit=1")
            self.noms[cle] = (d[0]["centre"]["coordinates"][::-1] + [d[0]["codeDepartement"]]
                              if d and d[0].get("centre") else None)
        return self.noms[cle]

    def departement_nomme(self, nom):
        """'Loire-Atlantique' -> '44' ; None si ce n'est pas exactement un nom de département."""
        cle = "dep:" + nom.strip().lower()
        if cle not in self.noms:
            d = self._get(f"{GEO}/departements?nom={requests.utils.quote(nom)}&limit=1")
            self.noms[cle] = d[0]["code"] if d and sans_accents(d[0]["nom"]) == sans_accents(nom) else None
        return self.noms[cle]

    def position_libre(self, o):
        """Pour les autres sources : (lat, lon, précision, département) à partir de ce qu'elles donnent
        — coordonnées, code postal, « Lyon (69) » ou seulement un nom de ville."""
        lieu = o.get("lieu") or ""
        dep = departement({"codePostal": o.get("cp") or ""})
        if not dep:
            m = re.search(r"\((\d{2}|2A|2B)\)", lieu)
            dep = m.group(1) if m else ""
        # Coordonnées et code postal connus (La bonne alternance) : rien à chercher de plus.
        if o.get("lat") is not None and o.get("lon") is not None and dep:
            return o["lat"], o["lon"], "offre", dep
        morceaux = [m.strip() for m in re.split(r"[,(]", lieu) if m.strip()]
        # « 1er Arrondissement, Paris » (Adzuna) : la ville est le morceau suivant.
        if len(morceaux) > 1 and re.search(r"arrondissement", morceaux[0], re.IGNORECASE):
            morceaux = morceaux[1:]
        nom = re.sub(r"^\d{5}\s+", "", morceaux[0] if morceaux else "")   # « 75001 Paris » -> « Paris »
        trouve = self.ville(nom) if nom and nom.lower() not in ("france", "télétravail", "teletravail") else None
        if not trouve and not dep and nom:
            # « Loire-Atlantique, Pays de la Loire » : un nom de département ; « La Défense, Courbevoie » :
            # un quartier, la ville vient ensuite (sauf si c'est une région).
            dep = self.departement_nomme(nom) or ""
            if not dep and len(morceaux) > 1 and sans_accents(morceaux[1]) not in REGIONS:
                trouve = self.ville(morceaux[1])
        if trouve and (not dep or trouve[2] == dep):
            dep = trouve[2]
        if o.get("lat") is not None and o.get("lon") is not None:
            return o["lat"], o["lon"], "offre", dep
        if trouve and trouve[2] == dep:
            return trouve[0], trouve[1], "commune", dep
        if dep:
            p = self.departement(dep)
            if p:
                return p[0], p[1], "departement", dep
        return None, None, None, dep

    def sauver(self):
        (self.dossier / "noms.json").write_text(json.dumps(self.noms, ensure_ascii=False), encoding="utf-8")
        (self.dossier / "communes.json").write_text(json.dumps(self.communes), encoding="utf-8")
        (self.dossier / "departements.json").write_text(json.dumps(self.departements), encoding="utf-8")


def main():
    jours = sorted((RACINE / "data" / "actives").glob("*.csv"))
    if not jours:
        raise SystemExit("Aucune extraction : lancez d'abord scripts/extraire.py")
    jour = jours[-1].stem
    with jours[-1].open(encoding="utf-8") as f:
        actives = [(r["rome"], r["id"]) for r in csv.DictReader(f)]
    ids_actifs = {i for _, i in actives}

    # Dernière version connue de chaque offre active (les fichiers sont lus dans l'ordre des mois).
    versions = {}
    for f in sorted((RACINE / "data" / "brut").glob("*/*.jsonl")):
        with f.open(encoding="utf-8") as fh:
            for ligne in fh:
                if ligne.strip():
                    v = json.loads(ligne)
                    if v["id"] in ids_actifs:
                        versions[v["id"]] = v
    nb_versions = sum(1 for f in (RACINE / "data" / "brut").glob("*/*.jsonl")
                      for l in f.open(encoding="utf-8") if l.strip())

    geo = Geocodeur()
    offres = []
    for rome, oid in actives:
        v = versions.get(oid)
        if not v:
            continue
        o = v["offre"]
        lieu = o.get("lieuTravail") or {}
        texte = (o.get("intitule") or "") + " " + (o.get("description") or "")
        t = texte.lower()
        smin, smax = salaire_min_max((o.get("salaire") or {}).get("libelle"))
        lat, lon, precision = geo.position(lieu)
        offres.append({
            "id": oid,
            "rome": rome,
            "intitule": o.get("intitule"),
            "entreprise": (o.get("entreprise") or {}).get("nom"),
            "lieu": lieu.get("libelle"),
            "dep": departement(lieu),
            "lat": lat, "lon": lon, "prec": precision,
            "contrat": o.get("typeContrat"),
            "experience": o.get("experienceLibelle"),
            "alternance": bool(o.get("alternance")),
            "stage": est_stage(o),
            "source": SOURCE_FT,
            "partenaire": partenaire(o),
            "salaire": (o.get("salaire") or {}).get("libelle"),
            "smin": smin, "smax": smax,
            "date": (o.get("dateCreation") or "")[:10],
            "vu_le": v["vu_le"],
            "url": (o.get("origineOffre") or {}).get("urlOrigine"),
            "outils": [nom for nom, rx in REGEX_OUTILS.items() if rx.search(t)],
            "teletravail": "télétravail" in t,
            "competences": [c.get("libelle") for c in o.get("competences") or [] if c.get("libelle")],
            "niveau": niveau(o.get("intitule")),
            "nature": nature(o),
            "exp_exige": o.get("experienceExige") or None,
            "exp_ans": exp_ans(o.get("experienceLibelle")),
            "qualification": o.get("qualificationLibelle") or None,
            "formation": formation(o),
            "secteur": o.get("secteurActiviteLibelle") or None,
            "temps": temps_travail(o),
            "postes": int(o.get("nombrePostes") or 1),
        })
    # Les autres sources, au format commun (scripts/autres_sources.py), ramenées au format de la page.
    for o in autres_sources.lire(jour):
        if o.get("rome") not in METIERS:
            continue
        t = ((o.get("intitule") or "") + " " + (o.get("description") or "")).lower()
        lat, lon, precision, dep = geo.position_libre(o)
        smin, smax = o.get("smin"), o.get("smax")
        smin = round(smin) if smin and SALAIRE_MIN <= smin <= SALAIRE_MAX else None
        smax = round(smax) if smax and SALAIRE_MIN <= smax <= SALAIRE_MAX else None
        offres.append({
            "id": o["id"], "rome": o["rome"], "intitule": o.get("intitule"),
            "entreprise": o.get("entreprise"), "lieu": o.get("lieu"), "dep": dep,
            "lat": lat, "lon": lon, "prec": precision,
            "contrat": o.get("contrat"), "experience": None,
            "alternance": bool(o.get("alternance")),
            "stage": bool(o.get("stage")) or stage_intitule(o.get("intitule"), o.get("nature")),
            "source": o["source"], "partenaire": None,
            "salaire": f"Annuel de {smin} Euros à {smax or smin} Euros" if smin else None,
            "smin": smin, "smax": smax or smin,
            "date": o.get("date") or jour, "vu_le": o.get("collecte") or jour, "url": o.get("url"),
            "outils": [nom for nom, rx in REGEX_OUTILS.items() if rx.search(t)],
            "teletravail": "télétravail" in t,
            "competences": [], "niveau": niveau(o.get("intitule")),
            "nature": o.get("nature") or "autre",
            "exp_exige": None, "exp_ans": None, "qualification": None, "formation": None,
            "secteur": None, "temps": None, "postes": 1,
        })
    geo.sauver()
    avant = len(offres)
    offres = dedoublonner(offres)

    # Série : par jour et par métier
    serie = defaultdict(dict)
    with (RACINE / "data" / "serie.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            serie[r["date"]][r["rome"]] = int(r["total"])

    resume = {
        "date": jour,
        "source": " + ".join(s for s in SOURCES if any(o["source"] == s for o in offres)),
        "requete": "France Travail : une requête codeROME par métier ; autres sources : voir « Limites »",
        "metiers": [{"code": c, "libelle": l, "groupe": g, "coche": k,
                     "actives": sum(1 for o in offres if o["rome"] == c)}
                    for c, (l, g, k) in METIERS.items()],
        # Les onglets du site : chacun a ses groupes de métiers, affichés et filtrés à part.
        "onglets": [{"id": i, "titre": t,
                     "groupes": [{"nom": g, "codes": codes, "coche": k} for g, (codes, k) in groupes.items()]}
                    for i, (t, groupes) in ONGLETS.items()],
        "outils": list(OUTILS),
        "sources": [s for s in SOURCES if any(o["source"] == s for o in offres)],
        # Dernière collecte de chaque source : le site l'affiche, et signale une source en retard.
        "collectes": {s: max(o["vu_le"] for o in offres if o["source"] == s) if s != SOURCE_FT else jour
                      for s in SOURCES if any(o["source"] == s for o in offres)},
        "contrats": {c: contrat_libelle(c)
                     for c in sorted({o["contrat"] for o in offres if o["contrat"]})},
        "niveaux": NIVEAUX_LIBELLES,
        "formations": FORMATIONS,
        "versions_conservees": nb_versions,
        "sans_position": sum(1 for o in offres if o["lat"] is None),
        "serie": [{"date": d, "par_metier": m} for d, m in sorted(serie.items())],
        "offres": offres,
    }
    sortie = RACINE / "data" / "resume.json"
    sortie.write_text(json.dumps(resume, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    prec = defaultdict(int)
    for o in offres:
        prec[o["prec"]] += 1
    print(f"Écrit : {sortie.relative_to(RACINE)} — {len(offres)} offres actives du {jour}, "
          f"{sortie.stat().st_size // 1024} Ko")
    print(f"Stages : {sum(o['stage'] for o in offres)} ; doublons entre sources retirés : {avant - len(offres)}")
    print("Par source : " + ", ".join(f"{s} {sum(o['source'] == s for o in offres)}" for s in SOURCES))
    print(f"Positions : {dict(prec)} ({geo.appels} appels geo.api.gouv.fr)")
    avec = [o for o in offres if o["smin"] is not None]
    part = 100 * len(avec) // len(offres) if offres else 0
    print(f"Salaire affiché par {len(avec)} offres sur {len(offres)} ({part} %)")


if __name__ == "__main__":
    main()
