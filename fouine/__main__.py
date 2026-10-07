"""Lancement de Fouine : `python -m fouine`, ou `Fouine.exe` sous Windows.

Par défaut, Fouine s'ouvre dans une fenêtre à lui ; `--navigateur` garde l'ancienne façon
(la page dans le navigateur). Si la fenêtre ne peut pas s'afficher, Fouine le dit et se
rabat sur le navigateur.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import threading
import time
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


def _retrouver_la_console() -> None:
    """Fouine.exe n'a pas de console à lui. Lancé depuis une invite de commandes (pour
    `--version`, `--autotest` ou `--help`), il écrit dans celle de l'invite."""
    if sys.platform != "win32" or sys.stdout is not None:
        return
    try:
        import ctypes

        if ctypes.windll.kernel32.AttachConsole(-1):
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")  # noqa: SIM115
            sys.stderr = sys.stdout
    except (OSError, AttributeError):
        pass


def _options(arguments):
    analyse = argparse.ArgumentParser(prog="fouine", description="Retrouver ses fichiers par le sens, en local.")
    analyse.add_argument("--donnees", help="dossier où ranger l'index, les réglages, le journal et les modèles")
    analyse.add_argument("--port", type=int, default=0, help="port local à utiliser (par défaut : un port libre)")
    analyse.add_argument(
        "--navigateur", action="store_true",
        help="ouvrir Fouine dans le navigateur au lieu de sa propre fenêtre",
    )
    analyse.add_argument(
        "--sans-navigateur", action="store_true",
        help="n'ouvrir ni fenêtre ni navigateur : l'adresse de la page est seulement écrite",
    )
    analyse.add_argument(
        "--autotest", action="store_true",
        help="vérifie que le programme est complet, sans réseau et sans toucher à vos données, puis s'arrête",
    )
    # Pour la chaîne de fabrication : ouvre la vraie fenêtre, la vérifie, puis la referme.
    analyse.add_argument("--essai-fenetre", action="store_true", help=argparse.SUPPRESS)
    analyse.add_argument("--capture", help=argparse.SUPPRESS)
    analyse.add_argument("--version", action="version", version=f"Fouine {__version__}")
    return analyse.parse_args(arguments)


def _attendre_sans_fenetre(serveur, boites) -> None:
    """Mode navigateur : Fouine tourne jusqu'à ce qu'on l'arrête."""
    if boites.sans_console():
        if boites.attendre_arret(
            "Fouine est ouvert dans votre navigateur.\n\n"
            "Laissez ce message affiché tant que vous utilisez Fouine.\n"
            "Pour arrêter Fouine, cliquez sur OK."
        ):
            return
    print(f"Page de Fouine : {serveur.adresse_complete}")
    print("Pour arrêter Fouine : Ctrl+C, ou fermez cette fenêtre.", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nFouine est arrêté.")


def main(arguments=None) -> int:
    _retrouver_la_console()
    _console_lisible()
    options = _options(arguments)

    if options.autotest:
        from .autotest import lancer

        try:
            return lancer()
        except Exception as erreur:
            print(f"Auto-test raté : {type(erreur).__name__} : {erreur}", flush=True)
            return 1

    from . import boites, journal as mod_journal
    from .journal import journal
    from .reglages import dossier_donnees

    provisoire = None
    if options.essai_fenetre:
        os.environ["FOUINE_SANS_BOITE"] = "1"  # vaut aussi pour le second lancement de l'essai
    if options.essai_fenetre and not options.donnees:
        provisoire = tempfile.TemporaryDirectory(prefix="fouine-essai-", ignore_cleanup_errors=True)
        options.donnees = provisoire.name
    dossier = Path(options.donnees).resolve() if options.donnees else dossier_donnees()
    fichier_journal = mod_journal.installer(dossier)
    code = 1
    try:
        code = _tourner(options, dossier, fichier_journal, boites, journal)
    except Exception as erreur:
        journal.exception("Fouine s'est arrêté sur une erreur")
        boites.erreur(
            f"Fouine s'est arrêté sur une erreur : {type(erreur).__name__} : {erreur}"
            + (f"\n\nLe détail est dans le journal :\n{fichier_journal}" if fichier_journal else "")
        )
    finally:
        mod_journal.fermer()
        if provisoire is not None:
            provisoire.cleanup()
    return code


def _tourner(options, dossier: Path, fichier_journal, boites, journal) -> int:
    from . import fenetre
    from .instance import Instance, reveiller

    instance = Instance(dossier)
    try:
        seul = instance.prendre()
    except OSError as erreur:
        boites.erreur(f"Fouine ne peut pas écrire dans son dossier de données :\n{dossier}\n\n{erreur}")
        return 1
    if not seul:
        if reveiller(dossier):
            journal.info("Fouine tournait déjà : sa fenêtre a été ramenée devant.")
            return 0
        boites.informer(
            "Fouine est déjà lancé (ou en train de démarrer) : regardez dans la barre des tâches.\n\n"
            "S'il ne répond plus, fermez-le depuis le Gestionnaire des tâches, puis relancez-le."
        )
        return 0

    index = serveur = fil = None
    try:
        try:
            from .embedding import Embedding
            from .images import EmbeddingImages
            from .index import Index
            from .serveur import Application, Serveur

            if options.essai_fenetre:
                from .factice import FauxEmbedding, FauxEmbeddingImages

                index = Index(dossier, FauxEmbedding(), FauxEmbeddingImages())
            else:
                index = Index(dossier, Embedding(dossier / "modele"), EmbeddingImages(dossier / "modele-images"))
            serveur = Serveur(Application(index, dossier), options.port)
        except Exception as erreur:
            journal.exception("Démarrage impossible")
            if isinstance(erreur, OSError) and options.port:
                raison = f"le port {options.port} est déjà pris par un autre programme, ou interdit"
            else:
                raison = f"{type(erreur).__name__} : {erreur}"
            boites.erreur(
                f"Fouine n'a pas pu démarrer : {raison}."
                + (f"\n\nLe détail est dans le journal :\n{fichier_journal}" if fichier_journal else "")
            )
            return 1
        serveur.cle_instance = instance.cle
        fil = threading.Thread(target=serveur.serve_forever, daemon=True)
        fil.start()
        instance.annoncer(serveur.server_address[1])
        journal.info("Fouine %s est lancé (port %s). Données : %s", __version__, serveur.server_address[1], dossier)
        if not boites.sans_console():
            print(f"Fouine {__version__} est lancé. Données rangées dans : {dossier}", flush=True)

        if options.sans_navigateur:
            _attendre_sans_fenetre(serveur, boites)
            return 0

        rapport: list[str] = []
        if not options.navigateur:
            essai = None
            if options.essai_fenetre:
                essai = fenetre.essai_automatique(serveur, dossier, options.capture, rapport)
            try:
                fenetre.ouvrir(serveur, essai)
            except fenetre.Indisponible as raison:
                if options.essai_fenetre:
                    rapport.append(f"RATÉ  la fenêtre ne s'est pas ouverte : {raison}")
                else:
                    boites.informer(
                        f"Fouine ne peut pas ouvrir sa fenêtre sur ce PC : {raison}.\n\n"
                        "Il va s'ouvrir dans votre navigateur à la place."
                    )
                    options.navigateur = True
        if options.essai_fenetre:
            print("Essai de la fenêtre de Fouine " + __version__)
            print("\n".join(rapport), flush=True)
            rate = not rapport or any(ligne.startswith("RATÉ") for ligne in rapport)
            print("Essai raté." if rate else "Essai réussi.", flush=True)
            journal.info("Essai de la fenêtre : %s", "raté" if rate else "réussi")
            return 1 if rate else 0
        if options.navigateur:
            serveur.premier_plan = lambda: webbrowser.open(serveur.adresse_complete)
            webbrowser.open(serveur.adresse_complete)
            _attendre_sans_fenetre(serveur, boites)
        return 0
    finally:
        # Arrêt propre : l'indexation s'arrête à la fin du fichier en cours, puis le serveur
        # et la base sont fermés. Ce qui était déjà lu reste dans l'index.
        if serveur is not None:
            serveur.application.arreter()
            serveur.application.attendre(20)
            if fil is not None:
                serveur.shutdown()
                fil.join(10)
            serveur.server_close()
        if index is not None:
            index.fermer()
        instance.liberer()
        journal.info("Fouine est arrêté.")


if __name__ == "__main__":
    sys.exit(main())
