#!/bin/sh
# Prépare Fouine (Linux, macOS) : crée un environnement Python à part et installe les dépendances.
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
echo
echo "Installation terminée. Lancez Fouine avec : ./lancer.sh"
