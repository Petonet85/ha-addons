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
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
