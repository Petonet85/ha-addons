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
pas de « mode degrade » a desarmer, donc pas d'oubli possible.

DEUX CLIENTS HTTP, DONC DEUX GREFFONS. C'est le piege de cette panne :
`prevoir.py` passe par `floodcast.sources.hubeau`, mais `collecte.py` a son
PROPRE client. N'envelopper que le premier donnait un resultat trompeur — la
prevision repartait pendant que l'archive restait gelee, et le journal se
contentait d'afficher « total ajoute : 0 ».

L'HISTORIQUE LONG NE BASCULE PAS. Vingt ans de mesures au pas fin pour
reconstituer des moyennes journalieres seraient demesures. On garde plutot
une copie durable du dernier resultat obtenu : un historique de vingt ans ne
change pas d'un jour a l'autre, et s'en servir pendant une panne est sans
consequence.
"""

import datetime
import json
import os
import shutil
import sys

# Cache jetable pour les appels de repli : le cache d'HydroPortail n'expire
# jamais — c'est voulu, une mesure de 2014 ne changera plus — mais cela
# figerait le temps reel. On lui donne donc un dossier a part, vide avant
# chaque appel, sans toucher au cache historique qui, lui, est precieux.
CACHE_JETABLE = "/tmp/repli_hydroportail"

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


def _serie_hydroportail(code, grandeur, jours, depot):
    """Serie temps reel depuis HydroPortail, dans les unites de Hub'Eau.

    HydroPortail veut un code de STATION (dix caracteres), alors que la
    chaine interroge parfois un code de SITE (huit) — le debit n'est publie
    que sur le site. Dans la nomenclature francaise, la station porte le code
    du site suivi de deux chiffres de rang ; le projet le confirme, tarage.py
    associe M7022410 a M702241010. On essaie donc, et l'on echoue si rien ne
    vient : une serie vide passerait pour une riviere a sec.
    """
    if depot not in sys.path:
        sys.path.insert(0, depot)
    import hydroportail as hp

    candidats = [code] if len(code) == 10 else [code + "10", code + "01"]
    fin = datetime.date.today() + datetime.timedelta(days=1)
    debut = fin - datetime.timedelta(days=max(jours, 1) + 1)
    ancien = hp.CACHE
    hp.CACHE = CACHE_JETABLE
    try:
        shutil.rmtree(CACHE_JETABLE, ignore_errors=True)
        for station in candidats:
            serie = hp.serie(station, grandeur, debut.strftime("%d/%m/%Y"),
                             fin.strftime("%d/%m/%Y"))
            if len(serie):
                if station != code:
                    print("    (site %s lu comme station %s)" % (code, station))
                return serie
        raise ValueError("aucune mesure pour %s [%s] sur HydroPortail"
                         % ("/".join(candidats), grandeur))
    finally:
        hp.CACHE = ancien


# --------------------------------------------------------------------------
# Greffon 1 : floodcast/sources/hubeau.py, utilise par la prevision
# --------------------------------------------------------------------------

def installer(g, depot=None):
    if g.get("_repli_installe"):
        return
    depot = depot or os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(g.get("__file__", ".")))))

    hubeau_tr = g["observations_tr"]
    hubeau_dj = g["debits_journaliers"]

    def observations_tr(code_entite, grandeur="H", days=30):
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
            serie = _serie_hydroportail(code_entite, grandeur, days, depot)
            ETAT["replis"] += 1
            print("  repli HydroPortail pour %s [%s] : %d points"
                  % (code_entite, grandeur, len(serie)))
            return serie
        except Exception as exc:                        # noqa: BLE001
            print("  repli impossible pour %s [%s] : %s" % (code_entite, grandeur, exc))
            raise
        finally:
            _etat_vers_disque(depot)

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
            _etat_vers_disque(depot)
            raise RuntimeError("Hub'Eau indisponible et aucune copie locale "
                               "de l'historique de %s" % code_entite)
        import pandas as pd
        serie = pd.read_csv(copie, index_col=0, parse_dates=True)["debit"]
        ETAT["copies"] += 1
        age = (datetime.datetime.now()
               - datetime.datetime.fromtimestamp(os.path.getmtime(copie))).days
        print("  copie locale de l'historique de %s : %d points, %d jour(s) d'age"
              % (code_entite, len(serie), age))
        _etat_vers_disque(depot)
        return serie

    g["observations_tr"] = observations_tr
    g["debits_journaliers"] = debits_journaliers
    g["_repli_installe"] = True


# --------------------------------------------------------------------------
# Greffon 2 : collecte.py, qui a son propre client HTTP
# --------------------------------------------------------------------------

def installer_collecte(g, depot=None):
    if g.get("_repli_collecte_installe"):
        return
    depot = depot or os.path.dirname(os.path.abspath(g.get("__file__", ".")))
    hubeau_recuperer = g["recuperer"]

    def recuperer(code, grandeur="H", taille=20000):
        try:
            lignes = hubeau_recuperer(code, grandeur, taille)
            if lignes:
                ETAT["hubeau"] = True
                _etat_vers_disque(depot)
                return lignes
            motif = "Hub'Eau a répondu sans aucune mesure"
        except Exception as exc:                        # noqa: BLE001
            motif = str(exc)[:160]

        ETAT["hubeau"] = False
        ETAT["motif"] = motif
        serie = _serie_hydroportail(code, grandeur, 30, depot)
        # L'archive est en CENTIMETRES pour la hauteur et en m3/s pour le
        # debit ; HydroPortail rend des metres et des m3/s.
        facteur = 100.0 if grandeur == "H" else 1.0
        lignes = [(code, t.strftime("%Y-%m-%dT%H:%M:%SZ"), float(v) * facteur)
                  for t, v in serie.items()]
        ETAT["replis"] += 1
        print("  repli HydroPortail pour %s [%s] : %d mesures"
              % (code, grandeur, len(lignes)))
        _etat_vers_disque(depot)
        return lignes

    g["recuperer"] = recuperer
    g["_repli_collecte_installe"] = True
