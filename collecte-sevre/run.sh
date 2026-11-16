#!/bin/bash
# Boucle de collecte pour la Sevre Nantaise.
#
# POURQUOI DES PROCESSUS COURTS plutot que « radar.py --boucle 5 » : sur une Pi
# a 2 Go, un processus resident garderait numpy, pandas et h5py en memoire en
# permanence, soit 150 a 250 Mo pris a Home Assistant. Ici chaque capture
# demarre, ecrit sa ligne et rend la memoire. Le cout est de deux secondes
# d'import, 288 fois par jour : negligeable sur quatre coeurs.
#
# POURQUOI CET ADD-ON EXISTE : GitHub Actions n'honore pas un cron de 5 minutes.
# Mesure du 15/11/2026 sur 60 executions : une toutes les 6 h 18 en mediane,
# soit 5 % de la lame d'eau radar captee. Le reste est perdu definitivement,
# l'API ne servant que le dernier quart d'heure.
set -uo pipefail

PY=/opt/venv/bin/python3
OPTIONS=/data/options.json
TRAVAIL=/share/collecte
# Le dossier de configuration de Home Assistant est monte sous /homeassistant
# quand l'add-on declare « homeassistant_config » (cas present). Sous l'ancien
# nom « config », il apparaissait sous /config — qui designe desormais le
# dossier de reglages propre a l'add-on. On essaie donc les deux, dans cet
# ordre, pour ne pas ecrire dans un dossier que Home Assistant ne sert pas.
if [ -d /homeassistant ]; then
  PAGES=/homeassistant/www/crue
else
  PAGES=/config/www/crue
fi

lire() {
  "$PY" - "$1" "$2" <<'PYEOF'
import json, sys
try:
    with open('/data/options.json', encoding='utf-8') as fh:
        v = json.load(fh).get(sys.argv[1])
except Exception:
    v = None
if v is None or v == '':
    print(sys.argv[2])
elif isinstance(v, bool):
    # Sans cela, un booleen JSON ressortirait « True » et aucune comparaison
    # shell avec « true » ne fonctionnerait.
    print('true' if v else 'false')
else:
    print(v)
PYEOF
}

journal() { printf '[%s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }

CLE=$(lire cle_meteofrance "")
INT_RADAR=$(lire intervalle_radar 300)
INT_COLLECTE=$(lire intervalle_collecte 21600)
INT_PREVISION=$(lire intervalle_prevision 21600)
HORIZON=$(lire horizon_h 72)
PUBLIER=$(lire publier_page true)
DEPOT=https://github.com/Petonet85/Collecte.git

journal "radar toutes les ${INT_RADAR}s, collecte toutes les ${INT_COLLECTE}s, prevision toutes les ${INT_PREVISION}s"

if [ -z "$CLE" ]; then
  journal "ATTENTION : aucune cle Meteo-France configuree. La capture radar sera ignoree,"
  journal "            le reste fonctionnera. Renseigne-la dans la configuration de l'add-on."
else
  export METEOFRANCE_API_KEY="$CLE"
fi

# Premiere mise en place : on clone le depot une seule fois. Aucune operation
# git ensuite — les fichiers s'accumulent dans la copie de travail, et c'est
# volontaire : rien n'est pousse tant que tu ne l'as pas demande.
if [ ! -d "$TRAVAIL/.git" ]; then
  journal "premier demarrage : recuperation du depot dans $TRAVAIL"
  mkdir -p "$(dirname "$TRAVAIL")"
  if ! git clone --depth 50 "$DEPOT" "$TRAVAIL" 2>&1; then
    journal "ECHEC du clonage. Verifie l'acces reseau de la Pi."
    sleep 60
    exit 1
  fi
fi
cd "$TRAVAIL" || exit 1
journal "depot pret : $(git log --oneline -1 2>/dev/null || echo 'inconnu')"

tache() {
  local nom="$1"; shift
  local debut; debut=$(date +%s)
  if timeout 900 "$PY" "$@" >/tmp/"$nom".log 2>&1; then
    journal "$nom : fait en $(( $(date +%s) - debut ))s"
  else
    journal "$nom : ECHEC ($(tail -3 /tmp/"$nom".log | tr '\n' ' '))"
  fi
}

publier() {
  [ "$PUBLIER" = "true" ] || return 0
  mkdir -p "$PAGES"
  for f in index.html carte.html tableau.json prevision.json historique.json fiabilite.json; do
    [ -f "docs/$f" ] && cp -f "docs/$f" "$PAGES/$f"
  done
  journal "page recopiee dans $PAGES (visible sur /local/crue/index.html)"
}

prochain_radar=0
prochaine_collecte=0
prochaine_prevision=0

while true; do
  maintenant=$(date +%s)

  if [ "$maintenant" -ge "$prochain_radar" ]; then
    [ -n "$CLE" ] && tache radar radar.py --depot donnees
    prochain_radar=$(( maintenant + INT_RADAR ))
  fi

  if [ "$maintenant" -ge "$prochaine_collecte" ]; then
    tache collecte collecte.py --depot donnees
    prochaine_collecte=$(( maintenant + INT_COLLECTE ))
  fi

  if [ "$maintenant" -ge "$prochaine_prevision" ]; then
    tache prevision prevoir.py --horizon "$HORIZON"
    # Confrontation des previsions passees aux observations. Apres la
    # prevision : celle qui vient d'etre emise est alors deja archivee, et
    # les echeances des precedentes sont desormais observables.
    if "$PY" /opt/fiabilite.py "$TRAVAIL" "$TRAVAIL/docs/fiabilite.json" \
         >/tmp/fiabilite.log 2>&1; then
      journal "fiabilite : $(tail -1 /tmp/fiabilite.log | sed 's/^ *//')"
    else
      journal "fiabilite : ECHEC ($(tail -2 /tmp/fiabilite.log | tr '\n' ' '))"
    fi
    publier
    prochaine_prevision=$(( maintenant + INT_PREVISION ))
  fi

  sleep 20
done
