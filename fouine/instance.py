"""Une seule instance de Fouine par dossier de données.

Fouine garde un verrou sur le fichier `fouine.verrou` tant qu'il tourne ; le système le
relâche tout seul si Fouine est tué. À côté, `instance.json` dit sur quel port il écoute
et donne une clé tirée au hasard : un second lancement s'en sert pour demander au premier
de ramener sa fenêtre devant, puis s'arrête. Cette clé ne permet rien d'autre : ce n'est
pas le jeton de la page.
"""

from __future__ import annotations

import http.client
import json
import os
import secrets
import sys
from pathlib import Path

NOM_VERROU = "fouine.verrou"
NOM_FICHIER = "instance.json"
# Nom connu de l'installateur Windows : il s'en sert pour demander de fermer Fouine avant
# une mise à jour ou une désinstallation.
MUTEX_WINDOWS = "Fouine.RomainC-lab.application"


class Instance:
    def __init__(self, dossier: Path):
        self.dossier = Path(dossier)
        self.cle = secrets.token_urlsafe(24)
        self._verrou = None
        self._mutex = None

    def prendre(self) -> bool:
        """Rend False si un autre Fouine tourne déjà sur ce dossier de données."""
        self.dossier.mkdir(parents=True, exist_ok=True)
        fichier = open(self.dossier / NOM_VERROU, "a+b")  # noqa: SIM115 - gardé ouvert exprès
        try:
            if sys.platform == "win32":
                import msvcrt

                fichier.seek(0)
                msvcrt.locking(fichier.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fichier.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fichier.close()
            return False
        self._verrou = fichier
        if sys.platform == "win32":
            import ctypes

            self._mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_WINDOWS)
        return True

    def annoncer(self, port: int) -> None:
        """Écrit où joindre cette instance."""
        fichier = self.dossier / NOM_FICHIER
        provisoire = fichier.with_suffix(".json.tmp")
        provisoire.write_text(json.dumps({"pid": os.getpid(), "port": port, "cle": self.cle}), encoding="utf-8")
        os.replace(provisoire, fichier)

    def liberer(self) -> None:
        if self._verrou is None:
            return
        try:
            (self.dossier / NOM_FICHIER).unlink()
        except OSError:
            pass
        self._verrou.close()  # fermer le fichier relâche le verrou
        self._verrou = None
        if self._mutex:
            import ctypes

            ctypes.windll.kernel32.CloseHandle(self._mutex)
            self._mutex = None


def reveiller(dossier: Path, delai: float = 5) -> bool:
    """Demande au Fouine qui tourne déjà de se montrer. Rend True s'il a répondu."""
    try:
        infos = json.loads((Path(dossier) / NOM_FICHIER).read_text(encoding="utf-8"))
        port, cle, pid = int(infos["port"]), str(infos["cle"]), int(infos["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if sys.platform == "win32":
        # Windows ne laisse un programme passer devant que si celui qui est devant l'y autorise.
        try:
            import ctypes

            ctypes.windll.user32.AllowSetForegroundWindow(pid)
        except (OSError, AttributeError):
            pass
    connexion = http.client.HTTPConnection("127.0.0.1", port, timeout=delai)
    try:
        connexion.request("POST", "/api/premier-plan", body=b"{}",
                          headers={"Content-Type": "application/json", "X-Fouine-Instance": cle})
        return connexion.getresponse().status == 200
    except (OSError, http.client.HTTPException, UnicodeError):
        return False
    finally:
        connexion.close()
