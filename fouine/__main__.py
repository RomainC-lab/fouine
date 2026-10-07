"""Lancement de Fouine : `python -m fouine`, ou `Fouine.exe` sous Windows."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from . import __version__


def _console_lisible() -> None:
    """Consoles Windows anciennes : pas d'erreur sur les accents."""
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _attendre_avant_de_fermer() -> None:
    """Programme Windows lancé d'un double-clic : sans cette pause, la fenêtre se ferme
    avant qu'on ait pu lire le message d'erreur."""
    if getattr(sys, "frozen", False) and sys.stdin is not None and sys.stdin.isatty():
        try:
            input("\nAppuyez sur Entrée pour fermer cette fenêtre.")
        except (EOFError, KeyboardInterrupt):
            pass


def main(arguments=None) -> int:
    analyse = argparse.ArgumentParser(prog="fouine", description="Retrouver ses fichiers par le sens, en local.")
    analyse.add_argument("--donnees", help="dossier où ranger l'index, les réglages et les modèles")
    analyse.add_argument("--port", type=int, default=0, help="port local à utiliser (par défaut : un port libre)")
    analyse.add_argument("--sans-navigateur", action="store_true", help="ne pas ouvrir le navigateur")
    analyse.add_argument(
        "--autotest", action="store_true",
        help="vérifie que le programme est complet, sans réseau et sans toucher à vos données, puis s'arrête",
    )
    analyse.add_argument("--version", action="version", version=f"Fouine {__version__}")
    _console_lisible()
    options = analyse.parse_args(arguments)

    if options.autotest:
        from .autotest import lancer

        try:
            return lancer()
        except Exception as erreur:
            print(f"Auto-test raté : {type(erreur).__name__} : {erreur}", flush=True)
            return 1

    try:
        from .embedding import Embedding
        from .images import EmbeddingImages
        from .index import Index
        from .reglages import dossier_donnees
        from .serveur import Application, Serveur

        dossier = Path(options.donnees) if options.donnees else dossier_donnees()
        index = Index(dossier, Embedding(dossier / "modele"), EmbeddingImages(dossier / "modele-images"))
        serveur = Serveur(Application(index, dossier), options.port)
    except Exception as erreur:
        print(f"Fouine n'a pas pu démarrer : {type(erreur).__name__} : {erreur}", flush=True)
        _attendre_avant_de_fermer()
        return 1
    print(f"Fouine {__version__} est lancé.")
    print(f"Données rangées dans : {dossier}")
    print(f"Page à ouvrir dans le navigateur : {serveur.adresse_complete}")
    print()
    print("Laissez cette fenêtre ouverte tant que vous utilisez Fouine.")
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
