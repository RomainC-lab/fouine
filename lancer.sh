#!/bin/sh
# Démarre Fouine (Linux, macOS).
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Fouine n'est pas encore installé : lancez d'abord ./installer.sh"
  exit 1
fi
exec .venv/bin/python -m fouine "$@"
