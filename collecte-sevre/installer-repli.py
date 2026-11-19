#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pose le repli automatique dans le depot clone. Idempotent.

Pourquoi un greffon plutot qu'une modification du depot « Collecte » :

  * Le depot est clone en lecture seule par l'add-on, et ses fichiers de
    donnees sont modifies en permanence par la chaine. Un « git pull » pour
    recuperer un correctif entrerait en conflit avec ces modifications
    locales a chaque fois.

  * Le greffon, lui, se reapplique tout seul a chaque demarrage. Si le clone
    est refait de zero, il revient. Il n'y a pas d'etat a maintenir.

DEUX POSES, parce qu'il y a deux clients HTTP dans ce projet :

  * `floodcast/sources/hubeau.py`, utilise par la prevision. Ajout EN FIN de
    fichier : un ajout en fin ne depend d'aucun contexte et ne peut donc pas
    s'appliquer de travers.

  * `collecte.py`, qui a son propre client. Ajout juste AVANT son point
    d'entree, le seul endroit ou « recuperer » est deja definie et ou le
    programme n'a pas encore commence.

    python3 installer-repli.py [dossier_du_depot] [chemin_de_repli.py]
"""

import os
import shutil
import sys

MARQUEUR = "# --- repli automatique Hub'Eau -> HydroPortail (ajoute par l'add-on) ---"

GREFFON_HUBEAU = "\n\n" + MARQUEUR + """
# Voir repli_hydroportail.py pour le detail. En cas d'echec on ne fait rien :
# une chaine sans repli vaut mieux qu'une chaine qui refuse de demarrer.
try:
    from .repli_hydroportail import installer as _installer_repli
    _installer_repli(globals())
except Exception as _exc:  # noqa: BLE001
    print("  repli non installe : " + str(_exc))
"""

MARQUEUR_COLLECTE = "# --- repli automatique pour collecte.py (ajoute par l'add-on) ---"

ANCRE_COLLECTE = 'if __name__ == "__main__":'

GREFFON_COLLECTE = MARQUEUR_COLLECTE + """
# collecte.py a son PROPRE client HTTP : envelopper floodcast ne suffit pas.
# Insere AVANT le point d'entree, pour que « recuperer » soit deja definie.
try:
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.join(
        _os.path.dirname(_os.path.abspath(__file__)), "floodcast", "sources"))
    from repli_hydroportail import installer_collecte as _installer_collecte
    _installer_collecte(globals())
except Exception as _exc:  # noqa: BLE001
    print("  repli collecte non installe : " + str(_exc))


"""


def poser_dans_hubeau(depot):
    chemin = os.path.join(depot, "floodcast", "sources", "hubeau.py")
    if not os.path.exists(chemin):
        print("  hubeau.py introuvable")
        return
    with open(chemin, encoding="utf-8") as fh:
        contenu = fh.read()
    if MARQUEUR in contenu:
        print("  repli prevision deja en place")
        return
    with open(chemin, "a", encoding="utf-8") as fh:
        fh.write(GREFFON_HUBEAU)
    print("  repli pose dans hubeau.py")


def poser_dans_collecte(depot):
    chemin = os.path.join(depot, "collecte.py")
    if not os.path.exists(chemin):
        print("  collecte.py introuvable")
        return
    with open(chemin, encoding="utf-8") as fh:
        contenu = fh.read()
    if MARQUEUR_COLLECTE in contenu:
        print("  repli collecte deja en place")
        return
    if ANCRE_COLLECTE not in contenu:
        print("  point d'entree de collecte.py introuvable : repli non pose")
        return
    contenu = contenu.replace(ANCRE_COLLECTE, GREFFON_COLLECTE + ANCRE_COLLECTE, 1)
    tmp = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(contenu)
    os.replace(tmp, chemin)
    print("  repli pose dans collecte.py")


def main(argv):
    depot = argv[1] if len(argv) > 1 else "/share/collecte"
    source = argv[2] if len(argv) > 2 else "/opt/repli.py"
    cible = os.path.join(depot, "floodcast", "sources", "repli_hydroportail.py")

    if not os.path.exists(source):
        print("  module de repli introuvable : " + source)
        return 0
    if not os.path.isdir(os.path.dirname(cible)):
        print("  depot incomplet : repli non pose")
        return 0

    # Le module est recopie a chaque fois : c'est l'add-on qui fait foi.
    shutil.copyfile(source, cible)
    poser_dans_hubeau(depot)
    poser_dans_collecte(depot)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
