"""Petites boîtes de message, pour le programme Windows qui n'a pas de console.

Ailleurs (ou si la boîte ne peut pas s'afficher), le message est écrit dans la console.
Dans tous les cas il va aussi dans le journal.
"""

from __future__ import annotations

import os
import sys

from .journal import journal

TITRE = "Fouine"
_OK, _ERREUR, _INFO, _DEVANT = 0x0, 0x10, 0x40, 0x10000


def sans_console() -> bool:
    """Vrai pour Fouine.exe lancé d'un double-clic : personne ne lirait un message écrit."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return ctypes.windll.kernel32.GetConsoleWindow() == 0
    except (OSError, AttributeError):
        return False


def _boite(texte: str, style: int) -> bool:
    # Pendant un essai automatique, personne n'est là pour cliquer sur OK.
    if os.environ.get("FOUINE_SANS_BOITE") or not sans_console():
        return False
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, texte, TITRE, style | _DEVANT)
        return True
    except (OSError, AttributeError):
        return False


def _ecrire(texte: str) -> None:
    try:
        print(texte, flush=True)
    except (OSError, ValueError):
        pass


def informer(texte: str) -> None:
    journal.info(texte)
    if not _boite(texte, _OK | _INFO):
        _ecrire(texte)


def erreur(texte: str) -> None:
    journal.error(texte)
    if not _boite(texte, _OK | _ERREUR):
        _ecrire(texte)


def attendre_arret(texte: str) -> bool:
    """Affiche `texte` avec un bouton OK et attend qu'on clique. Rend False sans boîte possible."""
    return _boite(texte, _OK | _INFO)
