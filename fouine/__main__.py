"""Lancement de Fouine : `python -m fouine`."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from . import __version__
from .embedding import Embedding
from .index import Index
from .reglages import dossier_donnees
from .serveur import Application, Serveur


def main(arguments=None) -> int:
    analyse = argparse.ArgumentParser(prog="fouine", description="Retrouver ses fichiers par le sens, en local.")
    analyse.add_argument("--donnees", help="dossier où ranger l'index, les réglages et le modèle")
    analyse.add_argument("--port", type=int, default=0, help="port local à utiliser (par défaut : un port libre)")
    analyse.add_argument("--sans-navigateur", action="store_true", help="ne pas ouvrir le navigateur")
    analyse.add_argument("--version", action="version", version=f"Fouine {__version__}")
    options = analyse.parse_args(arguments)

    for flux in (sys.stdout, sys.stderr):  # consoles Windows anciennes : pas d'erreur sur les accents
        try:
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    dossier = Path(options.donnees) if options.donnees else dossier_donnees()
    index = Index(dossier, Embedding(dossier / "modele"))
    serveur = Serveur(Application(index, dossier), options.port)
    print(f"Fouine {__version__} est lancé.")
    print(f"Données rangées dans : {dossier}")
    print(f"Page à ouvrir dans le navigateur : {serveur.adresse_complete}")
    print("Pour arrêter Fouine : fermez cette fenêtre (ou Ctrl+C).", flush=True)
    if not options.sans_navigateur:
        webbrowser.open(serveur.adresse_complete)
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("\nFouine est arrêté.")
    finally:
        serveur.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
