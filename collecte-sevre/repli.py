#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bascule automatique de Hub'Eau vers HydroPortail, et retour.

Le 18/11/2026 Hub'Eau a ete « suspendu pour raison de securite » : l'API
repondait HTTP 200 avec une page HTML de 900 ko au lieu du JSON. Toute la
chaine hydrometrique s'est arretee — seul le radar, qui passe par
Meteo-France, a continue.

Or les memes mesures existent ailleurs. HydroPortail (hydro.eaufrance.fr,
meme banque de donnees, service du SCHAPI) sert les trois stations du bassin
au pas fin, et il est reste debout pendant toute la panne.

PRINCIPE : Hub'Eau reste la source normale. On l'essaie a chaque appel, et
l'on ne bascule qu'en cas d'echec ou de reponse vide. Des que Hub'Eau
revient, il reprend la main sans que personne n'ait rien a faire — il n'y a
pas d'etat « mode degrade » a desarmer, donc pas d'oubli possible.

DEUX GRANDEURS, DEUX STRATEGIES :

  * Le temps reel (`observations_tr`) bascule sur HydroPortail, qui sert les
    memes mesures a la minute pres.

  * L'historique long des debits journaliers (`debits_journaliers`) ne
    bascule pas : vingt ans de mesures au pas fin representeraient des
    centaines de milliers de points pour reconstituer des moyennes
    journalieres. On garde plutot une copie durable du dernier resultat
    obtenu. Un historique de vingt ans ne change pas d'un jour a l'autre :
    s'en servir pendant une panne est sans consequence, et c'est exactement
    ce qui manquait le 19/11 pour que la prevision aboutisse.

Ce module est installe dans le depot clone par l'add-on, et appele depuis la
fin de `floodcast/sources/hubeau.py`.
"""

import datetime
import json
import os
import shutil

# Cache jetable pour les appels de repli : le cache d'HydroPortail n'expire
# jamais — c'est voulu, une mesure de 2014 ne changera plus — mais cela
# figerait le temps reel. On lui donne donc un dossier a part, vide avant
# chaque appel, sans toucher au cache historique qui, lui, est precieux.
CACHE_JETABLE = "/tmp/repli_hydroportail"

# Copie durable de l'historique long, a l'abri des pannes.
DOSSIER_COPIES = "donnees/repli"

ETAT = {"hubeau": None, "replis": 0, "motif": None, "copies": 0}


def _etat_vers_disque(depot):
    """Publie l'etat des sources, pour que la page puisse le dire."""
    try:
        chemin = os.path.join(depot, "docs", "sources.json")
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        tmp = chemin + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({
                "genere_le": datetime.datetime.now(datetime.timezone.utc)
                             .strftime("%Y-%m-%dT%H:%M:%SZ"),
                "hubeau_disponible": ETAT["hubeau"],
                "appels_en_repli": ETAT["replis"],
                "copies_utilisees": ETAT["copies"],
                "dernier_motif": ETAT["motif"],
            }, fh, ensure_ascii=False)
        os.replace(tmp, chemin)
    except Exception:                                   # noqa: BLE001
        pass


def installer(g, depot=None):
    """Enveloppe les deux fonctions de hubeau.py qui lisent des mesures."""
    if g.get("_repli_installe"):
        return
    depot = depot or os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(g.get("__file__", ".")))))

    hubeau_tr = g["observations_tr"]
    hubeau_dj = g["debits_journaliers"]

    def _hydroportail(code, grandeur, jours):
        import sys
        if depot not in sys.path:
            sys.path.insert(0, depot)
        import hydroportail as hp
        # HydroPortail veut un code de STATION (dix caracteres). Un code de
        # site n'a pas d'equivalent direct : on ne tente pas de deviner.
        if len(code) != 10:
            raise ValueError("code de site, pas de station : %s" % code)
        fin = datetime.date.today() + datetime.timedelta(days=1)
        debut = fin - datetime.timedelta(days=max(jours, 1) + 1)
        ancien = hp.CACHE
        hp.CACHE = CACHE_JETABLE
        try:
            shutil.rmtree(CACHE_JETABLE, ignore_errors=True)
            return hp.serie(code, grandeur, debut.strftime("%d/%m/%Y"),
                            fin.strftime("%d/%m/%Y"))
        finally:
            hp.CACHE = ancien

    def observations_tr(code_entite, grandeur="H", days=30):
        motif = None
        try:
            serie = hubeau_tr(code_entite, grandeur, days)
            if len(serie):
                ETAT["hubeau"] = True
                _etat_vers_disque(depot)
                return serie
            motif = "Hub'Eau a répondu sans aucune mesure"
        except Exception as exc:                        # noqa: BLE001
            motif = str(exc)[:160]

        ETAT["hubeau"] = False
        ETAT["motif"] = motif
        try:
            serie = _hydroportail(code_entite, grandeur, days)
            ETAT["replis"] += 1
            print("  repli HydroPortail pour %s [%s] : %d points (%s)"
                  % (code_entite, grandeur, len(serie), motif))
        except Exception as exc:                        # noqa: BLE001
            print("  repli impossible pour %s [%s] : %s" % (code_entite, grandeur, exc))
            raise
        finally:
            _etat_vers_disque(depot)
        return serie

    def debits_journaliers(code_entite, start="1990-01-01"):
        copie = os.path.join(depot, DOSSIER_COPIES,
                             "debits_journaliers_%s.csv" % code_entite)
        try:
            serie = hubeau_dj(code_entite, start)
            if len(serie):
                try:
                    os.makedirs(os.path.dirname(copie), exist_ok=True)
                    serie.to_csv(copie, header=["debit"])
                except Exception:                       # noqa: BLE001
                    pass
                return serie
            motif = "Hub'Eau a répondu sans aucune mesure"
        except Exception as exc:                        # noqa: BLE001
            motif = str(exc)[:160]

        ETAT["hubeau"] = False
        ETAT["motif"] = motif
        if not os.path.exists(copie):
            print("  aucune copie de l'historique de %s : %s" % (code_entite, motif))
            _etat_vers_disque(depot)
            raise RuntimeError("Hub'Eau indisponible et aucune copie locale "
                               "de l'historique de %s" % code_entite)
        import pandas as pd
        serie = pd.read_csv(copie, index_col=0, parse_dates=True)["debit"]
        ETAT["copies"] += 1
        age = (datetime.datetime.now() -
               datetime.datetime.fromtimestamp(os.path.getmtime(copie))).days
        print("  copie locale de l'historique de %s : %d points, %d jour(s) d'âge (%s)"
              % (code_entite, len(serie), age, motif))
        _etat_vers_disque(depot)
        return serie

    g["observations_tr"] = observations_tr
    g["debits_journaliers"] = debits_journaliers
    g["_repli_installe"] = True
