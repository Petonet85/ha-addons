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

Le greffon tient en deux gestes : copier le module de repli a cote de
hubeau.py, et ajouter trois lignes a la fin de hubeau.py. On ajoute A LA FIN
et non au milieu : un ajout en fin de fichier ne depend d'aucun contexte, et
ne peut donc pas s'appliquer de travers si le fichier change.

    python3 installer-repli.py [dossier_du_depot] [chemin_de_repli.py]
"""

import os
import shutil
import sys

MARQUEUR = "# --- repli automatique Hub'Eau -> HydroPortail (ajoute par l'add-on)"

GREFFON = '''

%s ---
# Voir repli_hydroportail.py pour le detail. En cas d'echec on ne fait rien :
# une chaine sans repli vaut mieux qu'une chaine qui refuse de demarrer.
try:
    from .repli_hydroportail import installer as _installer_repli
    _installer_repli(globals())
except Exception as _exc:  # noqa: BLE001
    print("  repli non installe : %%s" %% _exc)
''' % MARQUEUR


def main(argv):
    depot = argv[1] if len(argv) > 1 else "/share/collecte"
    source = argv[2] if len(argv) > 2 else "/opt/repli.py"
    cible_module = os.path.join(depot, "floodcast", "sources", "repli_hydroportail.py")
    hubeau = os.path.join(depot, "floodcast", "sources", "hubeau.py")

    if not os.path.exists(hubeau):
        print("  hubeau.py introuvable : repli non pose")
        return 0
    if not os.path.exists(source):
        print("  module de repli introuvable : %s" % source)
        return 0

    # 1. Le module, recopie a chaque fois : c'est l'add-on qui fait foi.
    os.makedirs(os.path.dirname(cible_module), exist_ok=True)
    shutil.copyfile(source, cible_module)

    # 2. L'appel, ajoute une seule fois.
    with open(hubeau, encoding="utf-8") as fh:
        contenu = fh.read()
    if MARQUEUR in contenu:
        print("  repli deja en place")
        return 0
    with open(hubeau, "a", encoding="utf-8") as fh:
        fh.write(GREFFON)
    print("  repli pose dans hubeau.py")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
