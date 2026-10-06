r"""Récupère les offres France Travail des métiers suivis et les enregistre dans data/.

Usage :
    .venv\Scripts\python.exe scripts\extraire.py                 # tous les métiers de METIERS
    .venv\Scripts\python.exe scripts\extraire.py --verifier      # teste seulement la connexion
    .venv\Scripts\python.exe scripts\extraire.py --rome M1718    # un seul code, pour essayer

Ce que ça écrit :
    data/brut/<AAAA-MM>/<ROME>.jsonl   une ligne par offre complète (JSON tel que l'API le renvoie),
                                       écrite la première fois qu'on voit l'offre, et de nouveau
                                       si son contenu a changé (une version = une ligne, datée)
    data/actives/<date>.csv            les offres actives ce jour-là : rome, id, date d'actualisation
    data/serie.csv                     une ligne par métier et par jour : total, nouvelles, modifiées

Les identifiants sont lus dans le fichier .env (voir .env.example) ou dans l'environnement
(secrets GitHub Actions). API : https://francetravail.io/data/api/offres-emploi —
150 offres par appel, 1 150 par requête, total réel dans l'en-tête Content-Range.

Les stages : l'API n'a pas de type de contrat « stage » (typeContrat = CDI, CDD, MIS, SAI, LIB…,
et natureContrat E2 = contrat d'apprentissage, pas un stage). Un stage publié sur France Travail
arrive donc sous un type de contrat quelconque, souvent CDI ou CDD, avec « Stage » dans l'intitulé.
La requête codeROME ne filtre aucun contrat : elle ramène déjà les stages. Si un métier dépasse
le plafond de 1 150 offres, une seconde requête codeROME + motsCles=stage rattrape ceux qui
seraient tombés au-delà. Le libellé « Stage » est posé par scripts/resumer.py (est_stage).
"""
import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

RACINE = Path(__file__).resolve().parent.parent
load_dotenv(RACINE / ".env")

# Le libellé affiché de chaque code ROME suivi.
LIBELLES = {
    # Cœur marketing
    "M1718": "Chargé(e) de marketing digital",
    "M1716": "Directeur(trice) marketing digital",
    "M1705": "Responsable marketing",
    "M1703": "Chef(fe) de produit",
    "M1620": "Assistant(e) marketing",
    "M1706": "Chef(fe) de promotion des ventes",
    "M1430": "Chargé(e) d'études commerciales",
    "M1711": "Directeur(trice) du marketing",
    # Digital, contenu, e-commerce
    "E1113": "Responsable e-commerce",
    "D1438": "Assistant(e) e-commerce",
    "E1101": "Community manager",
    "E1124": "Social media manager",
    "E1405": "Référenceur(se) web (SEO)",
    "M1886": "Chef(fe) de projet web",
    "M1426": "Chief digital officer",
    "M1719": "Chargé(e) des relations avec les influenceurs",
    "E1406": "Influenceur(se) web",
    # Communication et commerce, à la frontière
    "E1112": "Chargé(e) de communication",
    "E1103": "Chargé(e) des relations publiques",
    "E1107": "Chef(fe) de projet événementiel",
    "E1404": "Assistant(e) en publicité",
    "D1506": "Chargé(e) de merchandising",
    "D1415": "Chargé(e) de relation client (CRM)",
    # Commerce, achats, direction (onglets DCIB et Retail)
    "M1707": "Stratégie commerciale",
    "D1402": "Relation commerciale grands comptes et entreprises",
    "D1406": "Management en force de vente",
    "D1407": "Relation technico-commerciale",
    "D1401": "Assistanat commercial",
    "M1704": "Management relation clientèle",
    "M1101": "Achats",
    "M1102": "Direction des achats",
    "N1202": "Gestion des opérations de circulation internationale des marchandises",
    "M1302": "Direction de petite ou moyenne entreprise",
    "M1402": "Conseil en organisation et management d'entreprise",
    # Magasin et grande distribution (onglet Retail)
    "D1301": "Management de magasin de détail",
    "D1509": "Management de département en grande distribution",
    "D1502": "Management/gestion de rayon produits alimentaires",
    "D1503": "Management/gestion de rayon produits non alimentaires",
    "D1508": "Encadrement du personnel de caisses",
}

# Les onglets du site : identifiant -> (titre, groupes). Chaque groupe : nom -> (codes, coché par défaut).
# Un même code peut figurer dans plusieurs onglets : il n'est interrogé qu'une fois.
ONGLETS = {
    "marketing": ("Marketing & Digital", {
        "Marketing": (["M1718", "M1716", "M1705", "M1703", "M1620", "M1706", "M1430", "M1711"], True),
        "Digital": (["E1113", "D1438", "E1101", "E1124", "E1405", "M1886", "M1426", "M1719", "E1406"], True),
        "Frontière": (["E1112", "E1103", "E1107", "E1404", "D1506", "D1415"], False),
    }),
    "dcib": ("DCIB", {
        "Commercial": (["M1707", "D1402", "D1406", "D1407", "D1401", "M1704"], True),
        "Achats & international": (["M1101", "M1102", "N1202"], True),
        "Marketing & produit": (["M1705", "M1703"], True),
        "Direction & conseil": (["M1302", "M1402"], True),
    }),
    "retail": ("Retail", {
        "Magasin & grande distribution": (["D1301", "D1509", "D1502", "D1503", "D1508", "D1506"], True),
        "Commerce & marketing": (["D1406", "M1704", "M1705", "M1706", "M1703", "M1707"], True),
        "Achats & direction": (["M1101", "M1302"], True),
    }),
}

# Les métiers suivis : code ROME -> (libellé, groupe, coché par défaut), tirés du premier onglet
# où le code apparaît. C'est la liste qu'interroge la collecte.
METIERS = {}
for _titre, _groupes in ONGLETS.values():
    for _groupe, (_codes, _coche) in _groupes.items():
        for _code in _codes:
            METIERS.setdefault(_code, (LIBELLES[_code], _groupe, _coche))

TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire"
SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"

# Champs qui bougent sans que l'offre change : ignorés pour décider si une offre a été modifiée.
CHAMPS_VOLATILS = {"dateActualisation"}


def obtenir_token():
    cid, secret = os.getenv("FT_CLIENT_ID"), os.getenv("FT_CLIENT_SECRET")
    if not cid or not secret or cid.startswith("PAR_votre"):
        sys.exit("Identifiants absents : copiez .env.example en .env et remplissez-le.")
    r = requests.post(TOKEN_URL, data={
        "grant_type": "client_credentials",
        "client_id": cid,
        "client_secret": secret,
        "scope": "api_offresdemploiv2 o2dsoffre",
    }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def appeler(url, params, token, essais=3):
    """GET avec quelques nouvelles tentatives : une coupure réseau ou un 429/5xx passager ne doit
    pas faire perdre la journée. Au-delà, RuntimeError : l'appelant ignore ce métier et continue."""
    for i in range(essais):
        try:
            r = requests.get(url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        except requests.RequestException as e:
            erreur = f"réseau : {e.__class__.__name__}"
        else:
            if r.status_code not in (429, 500, 502, 503, 504):
                return r
            erreur = f"{r.status_code} : {r.text[:200]}"
        time.sleep(2 * (i + 1))
    raise RuntimeError(erreur)


def chercher(token, params, pas=150, maximum=1150):
    """Pagine la recherche ; renvoie (liste d'offres, total annoncé par l'API dans Content-Range)."""
    offres, total, debut = [], None, 0
    while debut < maximum:
        fin = min(debut + pas - 1, maximum - 1)
        r = appeler(SEARCH_URL, dict(params, range=f"{debut}-{fin}"), token)
        if r.status_code == 204:                     # aucune offre
            break
        if r.status_code not in (200, 206):
            raise RuntimeError(f"{r.status_code} : {r.text[:200]}")
        m = re.search(r"/(\d+)", r.headers.get("Content-Range", ""))   # ex. "offres 0-149/1234"
        if m:
            total = int(m.group(1))
        lot = r.json().get("resultats", [])
        offres.extend(lot)
        if len(lot) < pas or (total is not None and len(offres) >= total):
            break
        debut += pas
        time.sleep(0.3)                              # on reste poli avec l'API
    return offres, total


def empreinte(offre):
    """Empreinte du contenu d'une offre, champs volatils exclus : change si l'annonce change."""
    stable = {k: v for k, v in offre.items() if k not in CHAMPS_VOLATILS}
    return hashlib.sha1(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def versions_connues():
    """Toutes les (id, empreinte) déjà enregistrées dans data/brut, pour ne rien écrire deux fois."""
    vues = set()
    for f in (RACINE / "data" / "brut").glob("*/*.jsonl"):
        with f.open(encoding="utf-8") as fh:
            for ligne in fh:
                if ligne.strip():
                    v = json.loads(ligne)
                    vues.add((v["id"], v["empreinte"]))
    return vues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verifier", action="store_true", help="teste seulement la connexion")
    ap.add_argument("--rome", default="", help="un seul code ROME de METIERS, pour essayer")
    args = ap.parse_args()

    try:
        token = obtenir_token()
    except requests.RequestException as e:
        # Sortie en erreur, mais le workflow continue : le résumé se refait sur la dernière extraction.
        # La réponse du serveur dit pourquoi (invalid_client : identifiants refusés ; invalid_scope :
        # l'application n'est pas abonnée à l'API « Offres d'emploi v2 »). Elle ne contient aucun secret.
        reponse = getattr(e, "response", None)
        detail = (reponse.text or "")[:300] if reponse is not None else ""
        sys.exit(f"Connexion à l'API France Travail impossible : {e}" + (f" — réponse du serveur : {detail}" if detail else ""))
    print("Connexion à l'API France Travail : OK")
    if args.verifier:
        return
    codes = [args.rome] if args.rome else list(METIERS)
    if args.rome and args.rome not in METIERS:
        sys.exit(f"{args.rome} n'est pas dans METIERS (scripts/extraire.py).")

    aujourdhui = f"{date.today():%Y-%m-%d}"
    mois = aujourdhui[:7]
    vues = versions_connues()
    ids_connus = {i for i, _ in vues}
    (RACINE / "data" / "brut" / mois).mkdir(parents=True, exist_ok=True)
    (RACINE / "data" / "actives").mkdir(parents=True, exist_ok=True)

    actives, lignes_serie = [], []
    for code in codes:
        # Un code refusé par l'API (ex. retiré du référentiel) ne doit pas bloquer la veille des autres.
        try:
            offres, total = chercher(token, {"codeROME": code})
        except RuntimeError as e:
            print(f"{code}  {METIERS[code][0]:<48} ignoré — {e}")
            continue
        # Plafond de 1 150 atteint : les stages au-delà seraient perdus, on les demande à part.
        if total is not None and total > len(offres):
            try:
                deja = {o["id"] for o in offres}
                stages, _ = chercher(token, {"codeROME": code, "motsCles": "stage"})
                offres += [o for o in stages if o["id"] not in deja]
            except RuntimeError as e:
                print(f"{code}  complément « stage » ignoré — {e}")
        nouvelles = modifiees = 0
        with (RACINE / "data" / "brut" / mois / f"{code}.jsonl").open("a", encoding="utf-8") as brut:
            for o in offres:
                e = empreinte(o)
                if (o["id"], e) not in vues:
                    if o["id"] in ids_connus:
                        modifiees += 1
                    else:
                        nouvelles += 1
                        ids_connus.add(o["id"])
                    vues.add((o["id"], e))
                    brut.write(json.dumps({"id": o["id"], "empreinte": e, "vu_le": aujourdhui,
                                           "rome": code, "offre": o}, ensure_ascii=False) + "\n")
                actives.append((code, o["id"], (o.get("dateActualisation") or "")[:10]))
        lignes_serie.append([aujourdhui, code, total if total is not None else len(offres),
                             len(offres), nouvelles, modifiees])
        print(f"{code}  {METIERS[code][0]:<48} {len(offres):5d} offres, {nouvelles:4d} nouvelles, {modifiees:3d} modifiées")
        time.sleep(0.5)

    # Même logique pour les actives du jour : on remplace les codes relancés, on garde les autres.
    fichier_actives = RACINE / "data" / "actives" / f"{aujourdhui}.csv"
    if fichier_actives.exists():
        with fichier_actives.open(encoding="utf-8") as f:
            actives = [tuple(r) for r in list(csv.reader(f))[1:] if r[0] not in codes] + actives
    with fichier_actives.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rome", "id", "date_actualisation"])
        w.writerows(sorted(actives))

    serie = RACINE / "data" / "serie.csv"
    lignes = []
    if serie.exists():
        with serie.open(encoding="utf-8") as f:
            lignes = [r for r in csv.reader(f)][1:]
    # Si on relance le même jour, la ligne du jour est remplacée, pas doublée.
    lignes = [r for r in lignes if not (r[0] == aujourdhui and r[1] in codes)] + lignes_serie
    with serie.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "rome", "total", "recuperees", "nouvelles", "modifiees"])
        w.writerows(sorted(lignes))

    print(f"\n{aujourdhui} : {len(actives)} offres actives sur {len(codes)} métiers — "
          f"{sum(r[4] for r in lignes_serie)} nouvelles versions, {sum(r[5] for r in lignes_serie)} modifiées.")


if __name__ == "__main__":
    main()
