#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Recupere la prevision officielle de Vigicrues, quand il y en a une.

Saint-Laurent-sur-Sevre est une station de prevision officielle : le service
de l'Etat y publie sa propre prevision. Mais SEULEMENT PENDANT UN EPISODE.
Hors crue, l'API repond avec une structure complete et zero ligne — ce n'est
pas une panne, c'est l'etat normal neuf jours sur dix.

Avoir les deux previsions cote a cote a deux interets : voir si elles
s'accordent, et disposer de la reference officielle le jour ou la notre se
trompe. Aucune des deux ne remplace l'autre.

AVERTISSEMENT HONNETE : le format exact des lignes de prevision n'a pas pu
etre verifie sur des donnees reelles, aucune station du bassin n'etant en
crue au moment ou ce module a ete ecrit. La lecture des valeurs essaie donc
plusieurs noms de colonne connus, et le fichier produit indique toujours ce
qui a ete trouve. Le jour d'une vraie crue, il faudra le relire.

    python3 vigicrues.py [dossier_du_depot] [fichier_de_sortie]
"""

import datetime
import json
import os
import sys

# Saint-Laurent est la station de reference de la chaine ; Tiffauges est la
# premiere en aval, utile comme temoin independant.
STATIONS = (("M703243010", "Sèvre Nantaise à Saint-Laurent-sur-Sèvre"),
            ("M711241020", "Sèvre Nantaise à Tiffauges"))

# Noms de colonne rencontres dans les flux Vigicrues pour la valeur prevue.
# L'ordre compte : la moyenne d'abord, les bornes ensuite.
COLONNES = (("ResMoyPrev", "moyenne"), ("ResMinPrev", "basse"), ("ResMaxPrev", "haute"))

GRANDEURS = {1: ("hauteur", "m"), 2: ("débit", "m³/s"),
             "H": ("hauteur", "m"), "Q": ("débit", "m³/s")}


def maintenant():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def lire_station(code, nom, vigicrues):
    bloc = {"code": code, "nom": nom, "station_de_prevision": None,
            "prevision": None, "colonnes_vues": []}
    try:
        meta = (vigicrues.station(code) or {}).get("VigilanceCrues") or {}
        bloc["station_de_prevision"] = bool(meta.get("StationPrevision"))
    except Exception as exc:                           # noqa: BLE001
        bloc["erreur_station"] = str(exc)

    try:
        p = vigicrues.previsions(code) or {}
    except Exception as exc:                           # noqa: BLE001
        bloc["erreur_prevision"] = str(exc)
        return bloc

    df = p.get("series")
    grandeur, unite = GRANDEURS.get(p.get("grandeur"), ("valeur", ""))
    bloc["grandeur"] = grandeur
    bloc["unite"] = unite
    bloc["date_production"] = str(p.get("date_production") or "") or None

    if df is None or not len(df):
        bloc["prevision"] = {"points": [], "n": 0}
        return bloc

    bloc["colonnes_vues"] = [str(c) for c in df.columns]
    points = []
    for _, ligne in df.iterrows():
        t = ligne.get("DtPrev")
        if t is None:
            continue
        pt = {"t": str(t).replace(" ", "T")}
        for cle, nom_court in COLONNES:
            if cle in df.columns:
                try:
                    v = float(ligne[cle])
                except (TypeError, ValueError):
                    continue
                # Les hauteurs arrivent parfois en millimetres : au-dela de
                # vingt metres a cette echelle, c'est forcement le cas.
                if grandeur == "hauteur" and abs(v) > 20:
                    v /= 1000.0
                pt[nom_court] = round(v, 3)
        if len(pt) > 1:
            points.append(pt)
    points.sort(key=lambda x: x["t"])
    bloc["prevision"] = {"points": points, "n": len(points)}
    return bloc


def construire(depot):
    sys.path.insert(0, depot)
    from floodcast.sources import vigicrues

    stations = [lire_station(code, nom, vigicrues) for code, nom in STATIONS]
    total = sum((s.get("prevision") or {}).get("n", 0) for s in stations)
    return {
        "genere_le": maintenant(),
        "stations": stations,
        "n_points": total,
        "message": ("Aucune prévision officielle en ce moment. Vigicrues n'en publie "
                    "que pendant un épisode de crue : c'est l'état normal hors crue."
                    if not total else
                    "Prévision officielle disponible."),
    }


def main(argv):
    depot = argv[1] if len(argv) > 1 else "/share/collecte"
    sortie = argv[2] if len(argv) > 2 else os.path.join(depot, "docs", "vigicrues.json")
    try:
        d = construire(depot)
    except Exception as exc:                           # noqa: BLE001
        d = {"genere_le": maintenant(), "stations": [], "n_points": 0,
             "message": "Vigicrues injoignable : %s" % exc}
    os.makedirs(os.path.dirname(sortie), exist_ok=True)
    tmp = sortie + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False)
    os.replace(tmp, sortie)
    print("  vigicrues : %d points prevus -> %s" % (d.get("n_points", 0), sortie))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
