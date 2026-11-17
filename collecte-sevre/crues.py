#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rapatrie la FORME des crues marquantes, pas seulement leur maximum.

Le tableau de bord connaissait deja les cotes de pic des crues de reference
— 59,95 m en janvier 2025, par exemple. Mais une cote de pic ne dit pas si
l'eau est montee en six heures ou en deux jours, ni combien de temps elle
est restee haute. C'est pourtant ce qu'on veut savoir en regardant une
prevision monter : « est-ce que ca ressemble a janvier 2025 ? ».

Ce module extrait donc l'hydrogramme complet de chaque crue marquante, au
pas horaire, sur trois jours avant le pic et trois jours apres — la meme
fenetre que l'horizon de prevision.

TROIS PRECAUTIONS :

1. Les pics sont cherches dans l'historique journalier deja publie, puis le
   detail horaire est demande a HydroPortail. C'est la seule source qui
   serve des mesures anciennes au pas fin ; Hub'Eau ne garde qu'un mois.

2. Les reponses d'HydroPortail sont mises en cache sur disque par le module
   du projet : une crue de 2014 ne changera plus, et il n'y a aucune raison
   de redemander deux fois la meme chose a un service public. Ce programme
   ne refait donc du reseau que la premiere fois.

3. La conversion vers la cote a Rochereau utilise EXACTEMENT la meme
   relation que la prevision, decalage de bief compris. Une approximation
   maison donnerait des courbes qui ne se superposeraient pas correctement a
   la prevision, et l'ensemble perdrait tout interet.

    python3 crues.py [dossier_du_depot] [fichier_de_sortie]
"""

import datetime
import json
import os
import sys

STATION = "M703243010"

# Les trois stations du bassin, avec les grandeurs qu'HydroPortail sert pour
# chacune. Saint-Laurent n'a pas de debit en temps reel — ni historique
# exploitable : sa courbe de tarage est justement ce que la chaine reconstitue.
STATIONS = (
    ("M703243010", ("H",)),
    ("M702241010", ("H", "Q")),
    ("M704401010", ("H", "Q")),
)

# Nombre de crues retenues. Au-dela, le graphique devient un plat de
# spaghettis : six courbes superposables, c'est deja beaucoup.
N_CRUES = 6

# Deux pics separes de moins de quinze jours appartiennent au meme episode
# hydrologique : on ne garde que le plus haut.
ECART_MINIMUM_J = 15

# Fenetre autour du pic, en heures. Trois jours de part et d'autre : c'est
# l'horizon de la prevision, donc la duree comparable.
AVANT_H, APRES_H = 72, 72


def pics(historique):
    """Les crues marquantes, lues dans l'historique journalier deja publie."""
    z = (historique or {}).get("z_rochereau") or {}
    maxima = z.get("max") or []
    if not maxima or not z.get("debut"):
        return []
    debut = datetime.date.fromisoformat(z["debut"])
    jours = [(debut + datetime.timedelta(days=i), v)
             for i, v in enumerate(maxima) if v is not None]
    retenus = []
    for jour, valeur in sorted(jours, key=lambda x: -x[1]):
        if any(abs((jour - d).days) < ECART_MINIMUM_J for d, _ in retenus):
            continue
        retenus.append((jour, valeur))
        if len(retenus) >= N_CRUES:
            break
    return sorted(retenus)


MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre")


def nommer(jour):
    return "%s %d" % (MOIS[jour.month - 1], jour.year)


def autour_du_pic(index, valeurs, np, pd):
    """Recadre une serie sur son propre maximum, en heures relatives.

    Chaque station culmine a son heure : Saint-Mesmin avant Saint-Laurent,
    Saint-Laurent avant Rochereau. Caler chaque serie sur SON pic est ce qui
    permet de comparer des formes ; les caler toutes sur la meme horloge
    melangerait la forme et le temps de parcours.
    """
    if not len(valeurs):
        return None
    i = int(np.argmax(valeurs))
    t_pic = index[i]
    debut = t_pic - pd.Timedelta(hours=AVANT_H)
    fin = t_pic + pd.Timedelta(hours=APRES_H)
    heures, gardees = [], []
    for t, v in zip(index, valeurs):
        if debut <= t <= fin:
            heures.append(int(round((t - t_pic).total_seconds() / 3600)))
            gardees.append(round(float(v), 3))
    if len(heures) < 24:
        return None
    return {"h": heures, "v": gardees, "pic": round(float(valeurs[i]), 3),
            "date_pic": t_pic.strftime("%Y-%m-%dT%H:%M:%SZ")}


def stations_de_la_crue(jour, hp, pd, np):
    """Chaque station, dans sa propre unite, recadree sur son propre pic."""
    a = jour - datetime.timedelta(days=5)
    b = jour + datetime.timedelta(days=5)
    out = {}
    for code, grandeurs in STATIONS:
        bloc = {}
        for g in grandeurs:
            try:
                serie = hp.serie(code, g, a.strftime("%d/%m/%Y"), b.strftime("%d/%m/%Y"))
            except Exception:                          # noqa: BLE001
                continue
            if not len(serie):
                continue
            horaire = serie.resample("1h").mean().dropna()
            cadre = autour_du_pic(horaire.index, horaire.to_numpy(dtype=float), np, pd)
            if cadre:
                bloc["hauteur" if g == "H" else "debit"] = cadre
        if bloc:
            out[code] = bloc
    return out


def hydrogramme(jour, courbe, sevre, hp, pd, np):
    """L'hydrogramme horaire d'une crue, converti en cote a Rochereau."""
    a = jour - datetime.timedelta(days=5)
    b = jour + datetime.timedelta(days=5)
    serie = hp.serie(STATION, "H", a.strftime("%d/%m/%Y"), b.strftime("%d/%m/%Y"))
    if not len(serie):
        return None
    horaire = serie.resample("1h").mean().dropna()
    if len(horaire) < 24:
        return None

    # Le bief : ce qui passe a Rochereau est passe devant l'echelle 2,3 h plus
    # tot. Meme decalage que dans la chaine de prevision.
    decale = horaire.copy()
    decale.index = decale.index + pd.Timedelta(hours=sevre.retard_rochereau())
    cotes = sevre.niveau_rochereau(decale.to_numpy(dtype=float), courbe)

    i = int(np.argmax(cotes))
    t_pic = decale.index[i]
    debut = t_pic - pd.Timedelta(hours=AVANT_H)
    fin = t_pic + pd.Timedelta(hours=APRES_H)

    heures, valeurs = [], []
    for t, v in zip(decale.index, cotes):
        if debut <= t <= fin:
            heures.append(int(round((t - t_pic).total_seconds() / 3600)))
            valeurs.append(round(float(v), 3))
    if len(heures) < 24:
        return None
    return {
        "nom": nommer(jour),
        "date_pic": t_pic.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "z_pic": round(float(cotes[i]), 3),
        # Heures par rapport au pic : negatives avant, positives apres. C'est
        # ce decalage qui permet de superposer des crues d'annees differentes.
        "h": heures,
        "z": valeurs,
    }


def construire(depot):
    sys.path.insert(0, depot)
    import numpy as np
    import pandas as pd
    import hydroportail as hp
    from floodcast import sevre

    chemin = os.path.join(depot, "docs", "historique.json")
    with open(chemin, encoding="utf-8") as fh:
        historique = json.load(fh)

    courbe, _, _ = sevre.relation_transfert()
    crues = []
    for jour, _ in pics(historique):
        try:
            h = hydrogramme(jour, courbe, sevre, hp, pd, np)
        except Exception as exc:                       # noqa: BLE001
            print("  crue du %s ignoree (%s)" % (jour, exc))
            continue
        if not h:
            continue
        try:
            h["stations"] = stations_de_la_crue(jour, hp, pd, np)
        except Exception as exc:                       # noqa: BLE001
            h["stations"] = {}
            print("    stations amont indisponibles (%s)" % exc)
        crues.append(h)
        detail = ", ".join("%s %s" % (c, "+".join(sorted(b)))
                           for c, b in sorted((h.get("stations") or {}).items()))
        print("  %s : pic %.3f m NGF, %d heures | %s"
              % (h["nom"], h["z_pic"], len(h["h"]), detail or "aucune station"))

    crues.sort(key=lambda c: -c["z_pic"])
    return {
        "genere_le": datetime.datetime.now(datetime.timezone.utc)
                     .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "station": STATION,
        "fenetre_h": [-AVANT_H, APRES_H],
        "crues": crues,
    }


def main(argv):
    depot = argv[1] if len(argv) > 1 else "/share/collecte"
    sortie = argv[2] if len(argv) > 2 else os.path.join(depot, "docs", "crues.json")
    try:
        d = construire(depot)
    except Exception as exc:                           # noqa: BLE001
        d = {"genere_le": datetime.datetime.now(datetime.timezone.utc)
                          .strftime("%Y-%m-%dT%H:%M:%SZ"),
             "crues": [], "message": "Extraction impossible : %s" % exc}
    os.makedirs(os.path.dirname(sortie), exist_ok=True)
    tmp = sortie + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False)
    os.replace(tmp, sortie)
    print("  crues : %d hydrogrammes -> %s" % (len(d.get("crues") or []), sortie))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
