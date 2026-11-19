ARG BUILD_FROM
FROM ${BUILD_FROM}

# Pourquoi un environnement virtuel plutot que les paquets Debian : bookworm
# fournit pandas 1.5, alors que le depot exige pandas >= 2.0. pip, lui, trouve
# des roues aarch64 precompilees pour les quatre dependances — rien ne compile.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-venv git ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/venv/bin/pip install --no-cache-dir \
      "requests>=2.28" "numpy>=1.24" "pandas>=2.0" "h5py>=3.8" \
 && /opt/venv/bin/python3 -c "import numpy, pandas, h5py, requests; print('roues en place')"

COPY run.sh /run.sh
# Analyse de fiabilite : elle vit dans l'add-on et non dans le depot
# « Collecte », qui est clone en lecture seule et ne doit pas diverger.
COPY fiabilite.py /opt/fiabilite.py
# Hydrogrammes des crues marquantes : extraits une fois, puis relus
# depuis le cache disque du module HydroPortail du projet.
COPY crues.py /opt/crues.py
# Prevision officielle : vide hors episode, et c'est normal.
COPY vigicrues.py /opt/vigicrues.py
# Bascule automatique Hub'Eau -> HydroPortail, posee dans le depot clone
# a chaque demarrage. Voir repli.py pour le detail.
COPY repli.py /opt/repli.py
COPY installer-repli.py /opt/installer-repli.py
COPY amorcer-copies.py /opt/amorcer-copies.py
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
