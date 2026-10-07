"""Le journal de Fouine : `fouine.log`, dans le dossier de données.

Le programme Windows n'a plus de fenêtre noire : ce qui s'y affichait (erreurs, messages
des bibliothèques) est écrit ici. Le fichier est borné : au-delà de `TAILLE_MAX`, l'ancien
contenu passe dans `fouine.log.1`, qui remplace le précédent. Ni les questions tapées ni
le contenu des fichiers n'y sont écrits.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

NOM_FICHIER = "fouine.log"
TAILLE_MAX = 512 * 1024

journal = logging.getLogger("fouine")


class _VersLeJournal:
    """Remplace la console quand il n'y en a pas : chaque ligne écrite va dans le journal."""

    encoding = "utf-8"

    def __init__(self, niveau: int):
        self._niveau = niveau
        self._reste = ""
        self._occupe = False

    def write(self, texte) -> int:
        if not isinstance(texte, str):
            texte = bytes(texte).decode("utf-8", "replace")
        # Une barre de progression réécrit sa ligne avec « \r » : on ne garde que le dernier état.
        *lignes, self._reste = (self._reste + texte).replace("\r", "\n").split("\n")
        if self._occupe:  # le journal lui-même se plaint : ne pas tourner en rond
            return len(texte)
        self._occupe = True
        try:
            for ligne in lignes:
                if ligne.strip():
                    journal.log(self._niveau, ligne.rstrip())
        finally:
            self._occupe = False
        return len(texte)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


def installer(dossier: Path) -> Path | None:
    """Ouvre le journal dans `dossier` et y envoie aussi les erreurs que personne n'attrape.
    Rend le chemin du fichier, ou None s'il n'a pas pu être ouvert (Fouine marche quand même)."""
    fermer()
    journal.setLevel(logging.INFO)
    journal.propagate = False
    fichier: Path | None = Path(dossier) / NOM_FICHIER
    try:
        Path(dossier).mkdir(parents=True, exist_ok=True)
        sortie = RotatingFileHandler(fichier, maxBytes=TAILLE_MAX, backupCount=1, encoding="utf-8")
        sortie.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        journal.addHandler(sortie)
    except OSError:
        fichier = None
        journal.addHandler(logging.NullHandler())
    # Messages de la bibliothèque qui affiche la fenêtre : utiles si elle ne s'ouvre pas.
    fenetre = logging.getLogger("pywebview")
    fenetre.handlers[:] = journal.handlers
    fenetre.setLevel(logging.WARNING)
    fenetre.propagate = False

    if sys.stdout is None:
        sys.stdout = _VersLeJournal(logging.INFO)
    if sys.stderr is None:
        sys.stderr = _VersLeJournal(logging.WARNING)
        logging.raiseExceptions = False  # une panne du journal ne doit pas s'écrire… dans le journal
        # Sans console, la barre de progression des téléchargements remplirait le journal.
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

    def erreur_perdue(genre, erreur, trace):
        journal.error("Erreur inattendue", exc_info=(genre, erreur, trace))

    sys.excepthook = erreur_perdue
    threading.excepthook = lambda infos: erreur_perdue(infos.exc_type, infos.exc_value, infos.exc_traceback)
    return fichier


def fermer() -> None:
    """Referme le fichier (utile aux tests ; sous Windows, un fichier ouvert ne se supprime pas)."""
    for sortie in list(journal.handlers):
        journal.removeHandler(sortie)
        sortie.close()
    logging.getLogger("pywebview").handlers[:] = []
