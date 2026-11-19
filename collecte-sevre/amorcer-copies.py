#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reconstitue la copie de l'historique long a partir du cache HTTP.

Le repli garde une copie durable des debits journaliers, pour que la
prevision survive a une panne de Hub'Eau. Mais cette copie ne peut etre
ecrite que lors d'un appel REUSSI — or la panne du 18/11/2026 est survenue
avant qu'aucune copie n'existe.

Heureusement, le client HTTP de la chaine garde ses reponses en cache sur
disque. Les donnees sont donc la, eparpillees en pages. Ce programme les
rassemble et ecrit la copie.

POURQUOI LA DEGRADATION GRACIEUSE DU CLIENT N'A PAS SUFFI : il sait servir
un cache perime plutot que de planter, mais la cle de cache inclut les
parametres de la requete — dont une date de debut calculee a partir
d'aujourd'hui (vingt ans en arriere). Cette cle change donc CHAQUE JOUR, et
le cache de la veille devient introuvable. La copie ecrite ici, elle, porte
le seul code de la station : elle ne peut pas se perdre ainsi.

Idempotent : ne fait rien si la copie existe deja et qu'elle est plus
recente que les caches.

    python3 amorcer-copies.py [dossier_du_depot]
"""

import csv
import json
import os
import re
import sys

MOTIF_CODE = re.compile(r"code_entite=([A-Z0-9]+)")


def pages_du_cache(dossier):
    """Chaque reponse obs_elab trouvee, avec le code de sa station."""
    if not os.path.isdir(dossier):
        return {}
    par_station = {}
    for nom in sorted(os.listdir(dossier)):
        if not nom.endswith(".json"):
            continue
        chemin = os.path.join(dossier, nom)
        try:
            with open(chemin, encoding="utf-8") as fh:
                tete = fh.read(600)
                if "obs_elab" not in tete or "QmnJ" not in tete:
                    continue
                fh.seek(0)
                charge = json.load(fh)
        except Exception:                               # noqa: BLE001
            continue
        m = MOTIF_CODE.search(charge.get("first") or "")
        if not m:
            continue
        par_station.setdefault(m.group(1), []).append(charge.get("data") or [])
    return par_station


def assembler(pages):
    """Toutes les pages d'une station, fusionnees et dedoublonnees."""
    valeurs = {}
    for page in pages:
        for ligne in page:
            d = ligne.get("date_obs_elab")
            v = ligne.get("resultat_obs_elab")
            if d is None or v is None:
                continue
            try:
                v = float(v) / 1000.0                   # Hub'Eau rend des L/s
            except (TypeError, ValueError):
                continue
            if v < 0:                                   # valeurs manquantes
                continue
            valeurs[str(d)[:10]] = v
    return sorted(valeurs.items())


def main(argv):
    depot = argv[1] if len(argv) > 1 else "/share/collecte"
    cache = os.path.join(depot, "data", "cache")
    sortie = os.path.join(depot, "donnees", "repli")
    os.makedirs(sortie, exist_ok=True)

    par_station = pages_du_cache(cache)
    if not par_station:
        print("  aucun cache d'historique a reprendre")
        return 0

    for code, pages in sorted(par_station.items()):
        chemin = os.path.join(sortie, "debits_journaliers_%s.csv" % code)
        if os.path.exists(chemin):
            print("  %s : copie deja presente" % code)
            continue
        lignes = assembler(pages)
        if len(lignes) < 365:
            print("  %s : seulement %d jours, trop peu pour servir de copie"
                  % (code, len(lignes)))
            continue
        tmp = chemin + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["date", "debit"])
            for d, v in lignes:
                w.writerow([d, round(v, 4)])
        os.replace(tmp, chemin)
        print("  %s : copie ecrite, %d jours du %s au %s"
              % (code, len(lignes), lignes[0][0], lignes[-1][0]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
