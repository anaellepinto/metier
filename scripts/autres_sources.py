r"""Récupère les offres des sources officielles autres que France Travail et les enregistre, au
format commun, dans data/autres/<source>/<date>.jsonl (une offre par ligne).

Usage :
    .venv\Scripts\python.exe scripts\autres_sources.py                  # toutes les sources configurées
    .venv\Scripts\python.exe scripts\autres_sources.py --source adzuna  # une seule, pour essayer

Les trois sources, toutes par API officielle (pas de scraping) :
  - La bonne alternance (service public, API Apprentissage) : offres d'alternance, déjà classées
    par code ROME. Clé : LBA_API_KEY, à créer sur https://api.apprentissage.beta.gouv.fr/compte/profil
  - Adzuna (agrégateur) : toutes offres. Clés : ADZUNA_APP_ID et ADZUNA_APP_KEY, sur
    https://developer.adzuna.com (offre gratuite limitée à quelques centaines d'appels par jour).
  - Jooble (agrégateur) : toutes offres. Clé : JOOBLE_KEY, formulaire sur https://jooble.org/api/about

Adzuna et Jooble n'ont pas de code ROME : on les interroge avec un mot-clé par métier (MOTS_CLES)
et l'offre est rangée sous le code qui l'a trouvée. C'est une approximation, signalée sur le site.

Une source sans clé est ignorée ; une source en panne (réseau, quota, clé refusée) est notée et
les autres continuent. Le script ne sort jamais en erreur pour une source : la veille France
Travail et le déploiement ne dépendent pas de lui.

Format commun d'une offre (lu par scripts/resumer.py) :
    id, source, rome, intitule, entreprise, lieu, cp, lat, lon,
    contrat (CDI, CDD, MIS ou None), nature (apprentissage, professionnalisation, salarie ou None),
    alternance, stage, url, date (AAAA-MM-JJ), description (coupée), smin, smax (brut annuel)
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

RACINE = Path(__file__).resolve().parent.parent
load_dotenv(RACINE / ".env")
sys.path.insert(0, str(RACINE / "scripts"))
from extraire import METIERS  # noqa: E402  (la liste des métiers vit dans un seul fichier)

DOSSIER = RACINE / "data" / "autres"
GARDER_JOURS = 3            # fichiers conservés par source : le dépôt ne doit pas enfler
LONGUEUR_DESCRIPTION = 800  # assez pour repérer les outils cités, pas plus

# Mot-clé cherché sur Adzuna et Jooble pour chaque code ROME : l'intitulé qu'un recruteur écrit,
# pas le libellé du référentiel (« Gestion des opérations de circulation internationale… »).
MOTS_CLES = {
    "M1718": "chargé marketing digital", "M1716": "directeur marketing digital",
    "M1705": "responsable marketing", "M1703": "chef de produit marketing",
    "M1620": "assistant marketing", "M1706": "chef de promotion des ventes",
    "M1430": "chargé d'études marketing", "M1711": "directeur marketing",
    "E1113": "responsable e-commerce", "D1438": "assistant e-commerce",
    "E1101": "community manager", "E1124": "social media manager",
    "E1405": "consultant SEO", "M1886": "chef de projet web",
    "M1426": "chief digital officer", "M1719": "chargé marketing d'influence",
    "E1406": "influenceur", "E1112": "chargé de communication",
    "E1103": "chargé de relations presse", "E1107": "chef de projet événementiel",
    "E1404": "assistant publicité", "D1506": "merchandiser",
    "D1415": "chargé de relation client", "M1707": "directeur commercial",
    "D1402": "key account manager", "D1406": "manager commercial",
    "D1407": "technico-commercial", "D1401": "assistant commercial",
    "M1704": "responsable relation client", "M1101": "acheteur",
    "M1102": "directeur des achats", "N1202": "assistant import export",
    "M1302": "directeur de PME", "M1402": "consultant en organisation",
    "D1301": "responsable de magasin", "D1509": "chef de département grande distribution",
    "D1502": "manager rayon alimentaire", "D1503": "chef de rayon",
    "D1508": "responsable de caisses",
}

MOTIF_ALTERNANCE = re.compile(r"alternan|apprenti|contrat pro", re.IGNORECASE)
MOTIF_STAGE = re.compile(r"\bstag(e|iaire|iaires)\b|\binternship\b", re.IGNORECASE)
MOTIF_INTERIM = re.compile(r"int[ée]rim", re.IGNORECASE)
MOTIF_CDD = re.compile(r"\bcdd\b", re.IGNORECASE)
MOTIF_CDI = re.compile(r"\bcdi\b", re.IGNORECASE)
MOTIF_CP = re.compile(r"\b(\d{5})\b")


class Indisponible(Exception):
    """La source entière ne répond pas comme il faut (clé refusée, quota épuisé) : on l'arrête là."""


def appeler(methode, url, essais=3, **kw):
    """Requête avec quelques nouvelles tentatives sur coupure réseau ou 429/5xx passager."""
    erreur = ""
    for i in range(essais):
        try:
            r = requests.request(methode, url, timeout=30, **kw)
        except requests.RequestException as e:
            erreur = f"réseau : {e.__class__.__name__}"
        else:
            if r.status_code in (401, 403):
                raise Indisponible(f"accès refusé ({r.status_code}) : vérifiez la clé")
            if r.status_code not in (429, 500, 502, 503, 504):
                return r
            erreur = f"{r.status_code} : {r.text[:150]}"
        time.sleep(3 * (i + 1))
    if erreur.startswith("429"):
        raise Indisponible("quota atteint (429)")
    raise RuntimeError(erreur)


def contrat_depuis_texte(*textes):
    """(contrat, nature, alternance, stage) déduits de libellés libres : type annoncé + intitulé."""
    t = " ".join(x for x in textes if x)
    if MOTIF_ALTERNANCE.search(t):
        nat = "professionnalisation" if re.search(r"professionnalisation|contrat pro", t, re.I) else "apprentissage"
        return None, nat, True, False
    if MOTIF_STAGE.search(t):
        return None, None, False, True
    if MOTIF_INTERIM.search(t):
        return "MIS", "salarie", False, False
    if MOTIF_CDD.search(t):
        return "CDD", "salarie", False, False
    if MOTIF_CDI.search(t):
        return "CDI", "salarie", False, False
    return None, None, False, False


def couper(texte):
    t = re.sub(r"<[^>]+>", " ", texte or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:LONGUEUR_DESCRIPTION]


# ---------------------------------------------------------------- La bonne alternance

def la_bonne_alternance(codes):
    cle = os.getenv("LBA_API_KEY")
    url = "https://api.apprentissage.beta.gouv.fr/api/job/v1/search"
    for code in codes:
        try:
            r = appeler("GET", url, params={"romes": code}, headers={"Authorization": f"Bearer {cle}"})
            if r.status_code != 200:
                raise RuntimeError(f"{r.status_code} : {r.text[:150]}")
            jobs = r.json().get("jobs") or []
        except RuntimeError as e:
            print(f"  la bonne alternance {code} ignoré — {e}")
            continue
        n = 0
        for j in jobs:
            ident, offre = j.get("identifier") or {}, j.get("offer") or {}
            lieu = (j.get("workplace") or {}).get("location") or {}
            # Les offres France Travail relayées par La bonne alternance sont déjà dans la veille.
            if (ident.get("partner_label") or "").lower().startswith("france travail"):
                continue
            if offre.get("status") not in (None, "Active"):
                continue
            # Une offre dont la date d'expiration est passée n'est plus proposée.
            expire = ((offre.get("publication") or {}).get("expiration") or "")[:10]
            if expire and expire < f"{date.today():%Y-%m-%d}":
                continue
            types = " ".join((j.get("contract") or {}).get("type") or [])
            nat = "professionnalisation" if "rofessionnalisation" in types and "pprentissage" not in types else "apprentissage"
            coords = (lieu.get("geopoint") or {}).get("coordinates") or [None, None]
            adresse = lieu.get("address") or ""
            cp = MOTIF_CP.search(adresse)
            n += 1
            yield {
                "id": "lba-" + str(ident.get("id") or ident.get("partner_job_id")),
                "rome": code,
                "intitule": offre.get("title"),
                "entreprise": (j.get("workplace") or {}).get("name") or (j.get("workplace") or {}).get("brand"),
                "lieu": adresse, "cp": cp.group(1) if cp else None,
                "lat": coords[1], "lon": coords[0],
                "contrat": None, "nature": nat, "alternance": True, "stage": False,
                "url": (j.get("apply") or {}).get("url"),
                "date": ((offre.get("publication") or {}).get("creation") or "")[:10],
                "description": couper(offre.get("description")),
                "smin": None, "smax": None,
            }
        print(f"  la bonne alternance {code} : {n} offres")
        time.sleep(1.1)                          # 60 appels par minute au plus


# ---------------------------------------------------------------- Adzuna

ADZUNA_CONTRATS = {"permanent": "CDI", "contract": "CDD"}


def adzuna(codes):
    app_id, app_key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    pages = int(os.getenv("ADZUNA_PAGES", "1"))   # l'offre gratuite compte les appels : 1 page = 50 offres
    for code in codes:
        n = 0
        for page in range(1, pages + 1):
            try:
                r = appeler("GET", f"https://api.adzuna.com/v1/api/jobs/fr/search/{page}", params={
                    "app_id": app_id, "app_key": app_key, "what_phrase": MOTS_CLES[code],
                    "results_per_page": 50, "max_days_old": 30, "content-type": "application/json"})
                if r.status_code != 200:
                    raise RuntimeError(f"{r.status_code} : {r.text[:150]}")
                resultats = r.json().get("results") or []
            except RuntimeError as e:
                print(f"  adzuna {code} ignoré — {e}")
                break
            for o in resultats:
                contrat, nat, alt, stage = contrat_depuis_texte(o.get("title"))
                contrat = contrat or ADZUNA_CONTRATS.get(o.get("contract_type"))
                predit = str(o.get("salary_is_predicted")) == "1"   # salaire estimé par Adzuna : on ne l'affiche pas
                n += 1
                yield {
                    "id": "adzuna-" + str(o.get("id")),
                    "rome": code,
                    "intitule": o.get("title"),
                    "entreprise": (o.get("company") or {}).get("display_name"),
                    "lieu": (o.get("location") or {}).get("display_name"), "cp": None,
                    "lat": o.get("latitude"), "lon": o.get("longitude"),
                    "contrat": contrat, "nature": nat or ("salarie" if contrat else None),
                    "alternance": alt, "stage": stage,
                    "url": o.get("redirect_url"),
                    "date": (o.get("created") or "")[:10],
                    "description": couper(o.get("description")),
                    "smin": None if predit else o.get("salary_min"),
                    "smax": None if predit else o.get("salary_max"),
                }
            if len(resultats) < 50:
                break
            time.sleep(2.5)                      # 25 appels par minute au plus
        print(f"  adzuna {code} : {n} offres")
        time.sleep(2.5)


# ---------------------------------------------------------------- Jooble

def jooble(codes):
    cle = os.getenv("JOOBLE_KEY")
    for code in codes:
        try:
            r = appeler("POST", f"https://fr.jooble.org/api/{cle}",
                        json={"keywords": MOTS_CLES[code], "location": "France", "page": "1", "ResultOnPage": "50"})
            if r.status_code != 200:
                raise RuntimeError(f"{r.status_code} : {r.text[:150]}")
            jobs = r.json().get("jobs") or []
        except RuntimeError as e:
            print(f"  jooble {code} ignoré — {e}")
            continue
        for o in jobs:
            contrat, nat, alt, stage = contrat_depuis_texte(o.get("type"), o.get("title"))
            lieu = o.get("location") or ""
            cp = MOTIF_CP.search(lieu)
            yield {
                "id": "jooble-" + str(o.get("id")),
                "rome": code,
                "intitule": couper(o.get("title")),
                "entreprise": o.get("company") or None,
                "lieu": lieu, "cp": cp.group(1) if cp else None,
                "lat": None, "lon": None,
                "contrat": contrat, "nature": nat or ("salarie" if contrat else None),
                "alternance": alt, "stage": stage,
                "url": o.get("link"),
                "date": (o.get("updated") or "")[:10],
                "description": couper(o.get("snippet")),
                "smin": None, "smax": None,
            }
        print(f"  jooble {code} : {len(jobs)} offres")
        time.sleep(1)


# Source -> (nom affiché, collecteur, variables d'environnement nécessaires).
SOURCES = {
    "la-bonne-alternance": ("La bonne alternance", la_bonne_alternance, ["LBA_API_KEY"]),
    "adzuna": ("Adzuna", adzuna, ["ADZUNA_APP_ID", "ADZUNA_APP_KEY"]),
    "jooble": ("Jooble", jooble, ["JOOBLE_KEY"]),
}


def collecter(slug, codes, aujourdhui):
    nom, fonction, cles = SOURCES[slug]
    manquantes = [c for c in cles if not os.getenv(c)]
    if manquantes:
        print(f"{nom} : {', '.join(manquantes)} absent de l'environnement, source ignorée.")
        return
    print(f"{nom} :")
    flux = fonction(codes)
    offres, vues = [], set()
    try:
        for o in flux:
            if o["id"] in vues:                  # trouvée par deux mots-clés : on garde le premier métier
                continue
            vues.add(o["id"])
            offres.append(dict(o, source=nom))
    except Indisponible as e:
        print(f"{nom} interrompu — {e}")
    if not offres:
        print(f"{nom} : aucune offre, le fichier précédent est gardé.")
        return
    dossier = DOSSIER / slug
    dossier.mkdir(parents=True, exist_ok=True)
    with (dossier / f"{aujourdhui}.jsonl").open("w", encoding="utf-8") as f:
        for o in offres:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    for vieux in sorted(dossier.glob("*.jsonl"))[:-GARDER_JOURS]:
        vieux.unlink()
    print(f"{nom} : {len(offres)} offres enregistrées.")


def lire(jour, fraicheur=2):
    """Pour resumer.py : les offres de chaque source, lues dans son fichier le plus récent,
    s'il n'a pas plus de `fraicheur` jours de retard sur `jour` (sinon les offres sont périmées).
    Un fichier plus récent que `jour` est accepté : une source peut avoir tourné alors que la
    collecte France Travail, elle, a échoué."""
    limite = f"{date.fromisoformat(jour) - timedelta(days=fraicheur):%Y-%m-%d}"
    offres = []
    for slug in SOURCES:
        fichiers = [f for f in sorted((DOSSIER / slug).glob("*.jsonl")) if limite <= f.stem]
        if fichiers:
            with fichiers[-1].open(encoding="utf-8") as fh:
                # « collecte » : le jour où la source a été interrogée (affiché sur le site).
                offres += [dict(json.loads(l), collecte=fichiers[-1].stem) for l in fh if l.strip()]
    return offres


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=list(SOURCES), help="une seule source, pour essayer")
    args = ap.parse_args()
    aujourdhui = f"{date.today():%Y-%m-%d}"
    codes = [c for c in METIERS if c in MOTS_CLES]
    for slug in [args.source] if args.source else SOURCES:
        try:
            collecter(slug, codes, aujourdhui)
        except Exception as e:                   # une source qui plante ne bloque pas les suivantes
            print(f"{SOURCES[slug][0]} : erreur inattendue, source ignorée — {e!r}")


if __name__ == "__main__":
    main()
