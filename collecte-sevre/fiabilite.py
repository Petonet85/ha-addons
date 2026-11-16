#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Confronte les previsions emises a ce qui s'est reellement passe.

Pourquoi ce fichier plutot que « verification.py », qui existe deja dans le
projet et fait l'essentiel : celui-la va rechercher les observations sur
HydroPortail a chaque passage, alors que la Pi les archive deja toutes les
six heures, au pas de dix minutes, dans donnees/<station>/H/. Interroger un
service distant pour lire ce qu'on a sous la main serait lent, fragile, et
inutilement a la merci d'une panne chez autrui. Il ecrit aussi dans un
dossier « data/ » qui n'existe pas dans ce depot — le dossier s'appelle
« donnees ».

Ce module-ci ne lit donc que des fichiers locaux, n'a besoin d'aucune
bibliotheque, et ne sort jamais en erreur : un JSON valide est toujours
produit, quitte a dire qu'il n'y a pas encore de quoi conclure.

UNE PRECAUTION DE LECTURE, QUI EST TOUT L'INTERET DE LA CHOSE : ces chiffres
mesurent la chaine en conditions reelles, erreur de prevision de pluie
comprise. Ils seront donc moins flatteurs que les rejeux sur crues passees,
ou la pluie tombee est connue d'avance. C'est precisement ce qu'on veut
savoir.

    python3 fiabilite.py [dossier_du_depot] [fichier_de_sortie]
"""

import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone

STATION = "M703243010"          # Sevre Nantaise a Saint-Laurent-sur-Sevre

# Tranches d'echeance. Elles ne sont pas regulieres a dessein : l'erreur
# croit vite dans les premieres heures puis se stabilise, et une tranche
# « 1-6 h » dit quelque chose de tres different d'une tranche « 49-72 h ».
TRANCHES = [(1, 6, "1 à 6 h"), (7, 12, "7 à 12 h"), (13, 24, "13 à 24 h"),
            (25, 48, "25 à 48 h"), (49, 72, "49 à 72 h")]

# En dessous, les chiffres n'ont pas de sens : on les publie quand meme, mais
# accompagnes de leur effectif et d'un avertissement.
N_MINIMUM = 60

MAX_EPISODES = 8                # previsions detaillees gardees pour le trace

# Un abaissement du plan d'eau de Saint-Laurent (manoeuvre a la chaussee de
# Barbin) fait chuter l'echelle de 70 a 90 cm en quelques heures, sans pluie.
# Verifie le 16/11/2026 : pendant ces episodes la station amont de
# Saint-Mesmin ne bouge pas de plus de 2 cm. Le modele ne peut pas les
# prevoir, et les compter comme des erreurs de prevision reviendrait a lui
# reprocher de ne pas lire dans les pensees du gestionnaire de l'ouvrage.
#
# On les repere par rapport a la mediane glissante des sept jours precedents,
# et on publie les scores DANS LES DEUX CAS : tout compris, puis hors
# manoeuvre. Les ecarter sans le dire serait se flatter.
ABAISSEMENT_M = 0.30
FENETRE_MEDIANE_J = 7


# ----------------------------------------------------------------- outils --

def instant(txt):
    """Les horodatages sont en UTC, avec ou sans « Z »."""
    t = str(txt).strip().replace(" ", "T").replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def mediane(valeurs):
    v = sorted(valeurs)
    n = len(v)
    if not n:
        return None
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def moyenne(valeurs):
    return sum(valeurs) / len(valeurs) if valeurs else None


def quadratique(valeurs):
    return (sum(x * x for x in valeurs) / len(valeurs)) ** 0.5 if valeurs else None


def arrondi(v, n=1):
    return None if v is None else round(float(v), n)


# ------------------------------------------------------------- lectures ---

def observations(depot):
    """Hauteur observee, ramenee au pas horaire comme la prevision.

    Les releves sont au pas de dix minutes ; la prevision est horaire. On
    moyenne les releves de chaque heure plutot que d'en prendre un au hasard :
    un releve isole peut tomber sur un a-coup de la mesure.
    """
    dossier = os.path.join(depot, "donnees", STATION, "H")
    seaux = {}
    if not os.path.isdir(dossier):
        return {}
    for nom in sorted(os.listdir(dossier)):
        if not nom.endswith(".csv"):
            continue
        with open(os.path.join(dossier, nom), encoding="utf-8") as fh:
            for ligne in csv.DictReader(fh):
                d = instant(ligne.get("instant_utc"))
                if d is None:
                    continue
                try:
                    cm = float(ligne.get("hauteur_cm"))
                except (TypeError, ValueError):
                    continue
                seaux.setdefault(d.replace(minute=0, second=0, microsecond=0), []).append(cm)
    return {k: moyenne(v) / 100.0 for k, v in seaux.items()}      # en metres


def previsions(depot):
    dossier = os.path.join(depot, "donnees", "previsions")
    out = []
    if not os.path.isdir(dossier):
        return out
    for nom in sorted(os.listdir(dossier)):
        if not nom.endswith(".jsonl"):
            continue
        with open(os.path.join(dossier, nom), encoding="utf-8") as fh:
            for ligne in fh:
                try:
                    out.append(json.loads(ligne))
                except ValueError:
                    continue      # une ligne abimee ne doit pas tout perdre
    out.sort(key=lambda r: str(r.get("date_prevision")))
    return out


# ----------------------------------------------------------- confrontation --

def abaisse(obs, t):
    """L'echelle est-elle nettement sous son niveau habituel a cet instant ?"""
    debut = t - timedelta(days=FENETRE_MEDIANE_J)
    voisins = [v for k, v in obs.items() if debut <= k <= t]
    if len(voisins) < 48:                 # pas assez d'historique pour juger
        return False
    reel = obs.get(t)
    med = mediane(voisins)
    return reel is not None and med is not None and (med - reel) > ABAISSEMENT_M


def couples(runs, obs):
    """Un couple prevu/observe par echeance effectivement verifiable."""
    out, episodes = [], []
    for r in runs:
        t0 = instant(r.get("date_prevision"))
        serie = (r.get("h_saint_laurent") or {})
        med = serie.get("50") or []
        if t0 is None or not med:
            continue
        q25, q75 = serie.get("25") or [], serie.get("75") or []
        q10, q90 = serie.get("10") or [], serie.get("90") or []
        temps = [instant(t) for t in (r.get("time") or [])]

        ep = {"date_prevision": str(r.get("date_prevision")),
              "emise_le": r.get("genere_le"), "time": [], "prevu": [],
              "observe": [], "q10": [], "q90": []}
        for k, t in enumerate(temps):
            if t is None or k >= len(med):
                continue
            reel = obs.get(t)
            ep["time"].append(t.strftime("%Y-%m-%dT%H:%M:%SZ"))
            ep["prevu"].append(round(float(med[k]), 3))
            ep["observe"].append(None if reel is None else round(reel, 3))
            ep["q10"].append(round(float(q10[k]), 3) if k < len(q10) else None)
            ep["q90"].append(round(float(q90[k]), 3) if k < len(q90) else None)
            if reel is None:
                continue
            h = int(round((t - t0).total_seconds() / 3600))
            if h < 1 or h > 72:
                continue
            out.append({
                "echeance_h": h,
                "manoeuvre": abaisse(obs, t),
                "erreur_cm": 100.0 * (float(med[k]) - reel),
                "dans_50": (k < len(q25) and k < len(q75)
                            and float(q25[k]) <= reel <= float(q75[k])),
                "dans_80": (k < len(q10) and k < len(q90)
                            and float(q10[k]) <= reel <= float(q90[k])),
            })
        if any(v is not None for v in ep["observe"]):
            episodes.append(ep)
    return out, episodes


def score(lot):
    """Les quatre chiffres qui disent tout : combien, de combien, dispersion, honnetete."""
    err = [c["erreur_cm"] for c in lot]
    return {
        "n": len(lot),
        # Le biais : une chaine qui annonce systematiquement 10 cm de trop se
        # corrige d'un trait de plume ; une chaine dispersee, non.
        "biais_cm": arrondi(moyenne(err)),
        "erreur_mediane_cm": arrondi(mediane([abs(e) for e in err])),
        "rmse_cm": arrondi(quadratique(err)),
        # Le faisceau annonce « 8 chances sur 10 » : il doit contenir
        # l'observation 80 fois sur 100. Moins, il ment par optimisme ; plus,
        # il est si large qu'il ne dit plus rien.
        "dans_50_pct": arrondi(100.0 * moyenne([1.0 if c["dans_50"] else 0.0 for c in lot]), 0)
        if lot else None,
        "dans_80_pct": arrondi(100.0 * moyenne([1.0 if c["dans_80"] else 0.0 for c in lot]), 0)
        if lot else None,
    }


def construire(depot):
    obs = observations(depot)
    runs = previsions(depot)
    maintenant = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    base = {"genere_le": maintenant, "station": STATION,
            "n_previsions": len(runs), "n_observations_h": len(obs)}

    if not runs or not obs:
        base.update({"suffisant": False, "n_couples": 0, "par_tranche": [],
                     "par_echeance": [], "episodes": [],
                     "message": "Aucune prévision archivée n'a encore pu être confrontée "
                                "à une observation."})
        return base

    lot, episodes = couples(runs, obs)
    base["n_couples"] = len(lot)
    base["suffisant"] = len(lot) >= N_MINIMUM

    dates = sorted(str(r.get("date_prevision")) for r in runs)
    base["periode"] = {"premiere": dates[0], "derniere": dates[-1]}

    propre = [c for c in lot if not c["manoeuvre"]]
    base["n_manoeuvre"] = len(lot) - len(propre)
    base["global"] = score(lot) if lot else None
    base["global_hors_manoeuvre"] = score(propre) if propre else None

    base["par_tranche"] = [
        dict(tranche=nom,
             **score([c for c in lot if a <= c["echeance_h"] <= b]),
             hors_manoeuvre=score([c for c in propre if a <= c["echeance_h"] <= b]))
        for a, b, nom in TRANCHES]

    # Courbe fine : l'erreur heure par heure, pour voir ou elle decroche.
    base["par_echeance"] = []
    for h in range(1, 73):
        sous = [c for c in propre if c["echeance_h"] == h]
        if sous:
            base["par_echeance"].append({
                "h": h, "n": len(sous),
                "erreur_mediane_cm": arrondi(mediane([abs(c["erreur_cm"]) for c in sous])),
                "biais_cm": arrondi(moyenne([c["erreur_cm"] for c in sous])),
            })

    base["episodes"] = episodes[-MAX_EPISODES:]

    if not base["suffisant"]:
        base["message"] = (
            "Seulement %d comparaisons disponibles. L'archive se remplit de quatre "
            "prévisions par jour ; il en faut quelques semaines avant que ces "
            "chiffres veuillent dire quelque chose." % len(lot))
    else:
        base["message"] = (
            "Mesuré en conditions réelles, erreur de prévision de pluie comprise — "
            "donc moins flatteur, et plus honnête, qu'un rejeu sur crues passées.")
    return base


def main(argv):
    depot = argv[1] if len(argv) > 1 else "/share/collecte"
    sortie = argv[2] if len(argv) > 2 else os.path.join(depot, "docs", "fiabilite.json")
    try:
        d = construire(depot)
    except Exception as exc:                     # noqa: BLE001
        d = {"genere_le": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "suffisant": False, "n_couples": 0, "par_tranche": [], "par_echeance": [],
             "episodes": [], "message": "Analyse impossible : %s" % exc}
    os.makedirs(os.path.dirname(sortie), exist_ok=True)
    tmp = sortie + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False)
    os.replace(tmp, sortie)                      # remplacement atomique
    print("  fiabilite : %d previsions, %d comparaisons -> %s"
          % (d.get("n_previsions", 0), d.get("n_couples", 0), sortie))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
