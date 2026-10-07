"""Le petit serveur qui affiche l'interface dans le navigateur.

Il n'écoute que sur 127.0.0.1 : seul ce PC peut lui parler. Trois protections
en plus, contre une page web malveillante ouverte dans le même navigateur ou un
autre programme du PC :
- l'en-tête Host doit être 127.0.0.1 ou localhost, avec le bon port ;
- l'en-tête Origin, s'il est présent, doit être celui de Fouine ;
- chaque action demande un jeton secret, tiré au hasard à chaque lancement et
  transmis au navigateur dans l'adresse d'ouverture.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import string
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from . import __version__, filtres, reglages as mod_reglages
from .embedding import TAILLE_MODELE
from .images import TAILLE_MODELE_IMAGES


def _dossier_web() -> Path:
    """Les fichiers de l'interface ; dans le programme Windows tout fait, ils sont embarqués."""
    embarque = getattr(sys, "_MEIPASS", None)
    if embarque and (Path(embarque) / "fouine" / "web").is_dir():
        return Path(embarque) / "fouine" / "web"
    return Path(__file__).parent / "web"


DOSSIER_WEB = _dossier_web()
_STATIQUES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}
_CORPS_MAX = 1024 * 1024
_SECURITE = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self' data: blob:; form-action 'none'; frame-ancestors 'none'; base-uri 'none'"
)
# Types de fichiers qu'on n'ouvre jamais d'un clic : ce sont des programmes.
_PROGRAMMES = {
    ".exe", ".bat", ".cmd", ".com", ".msi", ".scr", ".pif", ".lnk", ".ps1", ".vbs", ".vbe", ".js", ".jse",
    ".wsf", ".wsh", ".hta", ".jar", ".reg", ".cpl", ".dll", ".sh", ".py", ".pyw", ".app", ".command", ".desktop",
}


class Refus(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def ouvrir_sur_le_pc(chemin: str, quoi: str) -> None:
    """Ouvre un fichier avec son logiciel habituel, ou montre son dossier."""
    if quoi == "dossier":
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(chemin)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", chemin])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(chemin)])
    elif sys.platform == "win32":
        os.startfile(chemin)  # noqa: S606 - chemin tiré de l'index, jamais un programme
    elif sys.platform == "darwin":
        subprocess.Popen(["open", chemin])
    else:
        subprocess.Popen(["xdg-open", chemin])


class Application:
    """Ce que l'interface peut demander. Ne connaît rien du réseau."""

    def __init__(self, index, dossier_donnees: Path, ouvrir=ouvrir_sur_le_pc):
        self.index = index
        self.dossier = Path(dossier_donnees)
        self.ouvrir_sur_le_pc = ouvrir
        self._verrou = threading.Lock()
        self._arret = threading.Event()
        self._fil: threading.Thread | None = None
        self.tache = {"en_cours": False, "etape": "", "fait": 0, "total": 0, "fichier": "", "reste_s": None, "bilan": None,
                      "erreur": None}

    # -- réglages

    def reglages(self) -> dict:
        return mod_reglages.charger(self.dossier)

    def etat(self, _=None) -> dict:
        return {
            "version": __version__,
            "reglages": self.reglages(),
            "dossiers_proposes": mod_reglages.dossiers_proposes(),
            "fichier_reglages": str(self.dossier / mod_reglages.NOM_FICHIER),
            "index": self.index.statistiques(),
            "tache": dict(self.tache),
            "taille_modele": TAILLE_MODELE,
            "taille_modele_images": TAILLE_MODELE_IMAGES,
        }

    def enregistrer(self, corps: dict) -> dict:
        if self.tache["en_cours"]:
            raise Refus(409, "Une indexation est en cours. Attendez la fin ou arrêtez-la.")
        recu = corps.get("reglages")
        if not isinstance(recu, dict):
            raise Refus(400, "Réglages manquants.")
        if recu.get("defaut") is True:
            # Les filtres reviennent à l'origine ; les dossiers choisis et le choix de lire
            # ou non les images sont gardés.
            actuels = self.reglages()
            nouveaux = mod_reglages.reglages_par_defaut()
            nouveaux["dossiers"] = actuels["dossiers"]
            nouveaux["lire_images"] = actuels["lire_images"]
        else:
            # L'interface ne modifie pas la liste des fichiers sensibles : elle reste
            # celle du fichier de réglages.
            actuels = self.reglages()
            nouveaux = dict(recu)
            nouveaux["motifs_sensibles"] = actuels["motifs_sensibles"]
            nouveaux["chemins_sensibles"] = actuels["chemins_sensibles"]
        return {"reglages": mod_reglages.enregistrer(nouveaux, self.dossier)}

    def dossiers(self, corps: dict) -> dict:
        """Liste les sous-dossiers d'un dossier, pour choisir quoi indexer."""
        demande = corps.get("chemin")
        if demande == "" and sys.platform == "win32":
            disques = [f"{lettre}:\\" for lettre in string.ascii_uppercase if os.path.exists(f"{lettre}:\\")]
            return {"chemin": "", "parent": None, "sous_dossiers": [{"nom": d, "chemin": d} for d in disques]}
        if not isinstance(demande, str) or not demande:
            demande = os.path.expanduser("~")
        chemin = os.path.abspath(demande)
        if not os.path.isdir(chemin):
            raise Refus(404, "Ce dossier n'existe pas.")
        sous_dossiers = []
        try:
            with os.scandir(chemin) as entrees:
                for entree in entrees:
                    try:
                        if entree.is_dir() and not filtres._est_cache(entree):
                            sous_dossiers.append({"nom": entree.name, "chemin": entree.path})
                    except OSError:
                        continue
        except OSError:
            raise Refus(403, "Ce dossier ne peut pas être ouvert.") from None
        sous_dossiers.sort(key=lambda d: d["nom"].lower())
        parent = os.path.dirname(chemin)
        if parent == chemin:
            parent = "" if sys.platform == "win32" else None
        return {"chemin": chemin, "parent": parent, "sous_dossiers": sous_dossiers}

    # -- aperçu, indexation

    def apercu(self, _=None) -> dict:
        dimensions, deja_lu = self.index.memoire()
        apercu = filtres.apercu(self.reglages(), dimensions_connues=dimensions, deja_lu=deja_lu, dossier_fouine=self.dossier
        )
        # Durée annoncée seulement si la vitesse a déjà été mesurée sur ce PC.
        vitesse = self.index.statistiques()["secondes_par_image"]
        a_lire = apercu["acceptes"]["images_a_lire"]
        apercu["duree_images_s"] = round(vitesse * a_lire) if vitesse is not None and a_lire else None
        return apercu

    def indexer(self, _=None) -> dict:
        with self._verrou:
            if self.tache["en_cours"]:
                raise Refus(409, "Une indexation est déjà en cours.")
            reglages = self.reglages()
            if not reglages["dossiers"]:
                raise Refus(400, "Choisissez d'abord au moins un dossier.")
            self._arret.clear()
            self.tache.update(
                en_cours=True, etape="parcours", fait=0, total=0, fichier="", reste_s=None, bilan=None, erreur=None
            )
            self._fil = threading.Thread(target=self._travail, args=(reglages,), daemon=True)
            self._fil.start()
        return {"tache": dict(self.tache)}

    def _travail(self, reglages: dict) -> None:
        try:
            if not self.index.embedding.pret():
                self.tache.update(etape="modele")
                self.index.embedding.vecteurs(["bonjour"])
            bilan = self.index.indexer(
                reglages, progression=lambda **infos: self.tache.update(infos), arret=self._arret.is_set
            )
            self.tache.update(bilan=bilan)
        except Exception as erreur:  # montré dans l'interface plutôt que perdu dans la console
            self.tache.update(erreur=f"{type(erreur).__name__} : {erreur}")
        finally:
            self.tache.update(en_cours=False, etape="", fichier="", reste_s=None)
            self.index.fermer()

    def arreter(self, _=None) -> dict:
        self._arret.set()
        return {"tache": dict(self.tache)}

    def attendre(self, delai: float = 60) -> None:
        if self._fil is not None:
            self._fil.join(delai)

    # -- recherche, ouverture

    def recherche(self, corps: dict) -> dict:
        question = corps.get("question")
        if not isinstance(question, str):
            raise Refus(400, "Question manquante.")
        return {"resultats": self.index.rechercher(question)}

    def recherche_images(self, corps: dict) -> dict:
        """À part de la recherche de documents : le second modèle met plus de temps à répondre."""
        question = corps.get("question")
        if not isinstance(question, str):
            raise Refus(400, "Question manquante.")
        return {"images": self.index.rechercher_images(question)}

    def vignette(self, identifiant: str) -> bytes:
        """La petite copie d'une image de l'index, et de rien d'autre."""
        if not identifiant.isascii() or not identifiant.isdigit() or len(identifiant) > 12:
            raise Refus(400, "Demande incomprise.")
        contenu = self.index.vignette(int(identifiant))
        if contenu is None:
            raise Refus(404, "Cette image n'est pas dans l'index.")
        return contenu

    def illisibles(self, _=None) -> dict:
        return {"illisibles": self.index.illisibles()}

    def ouvrir(self, corps: dict) -> dict:
        """N'ouvre qu'un fichier présent dans l'index, désigné par son numéro."""
        quoi = corps.get("quoi")
        if quoi not in ("fichier", "dossier"):
            raise Refus(400, "Demande incomprise.")
        chemin = self.index.chemin(corps.get("id"))
        if chemin is None:
            raise Refus(404, "Ce fichier n'est pas dans l'index.")
        if not os.path.exists(chemin):
            raise Refus(404, "Ce fichier n'existe plus à cet endroit. Relancez l'indexation.")
        if quoi == "fichier" and os.path.splitext(chemin)[1].lower() in _PROGRAMMES:
            raise Refus(403, "Par prudence, Fouine n'ouvre pas ce type de fichier. Ouvrez plutôt son dossier.")
        try:
            self.ouvrir_sur_le_pc(chemin, quoi)
        except OSError:
            raise Refus(500, "L'ouverture n'a pas marché sur ce PC.") from None
        return {"ok": True}

    ACTIONS = {
        "enregistrer": enregistrer,
        "dossiers": dossiers,
        "apercu": apercu,
        "indexer": indexer,
        "arreter": arreter,
        "recherche": recherche,
        "recherche_images": recherche_images,
        "illisibles": illisibles,
        "ouvrir": ouvrir,
    }


class Gestionnaire(BaseHTTPRequestHandler):
    server_version = "Fouine"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # rien dans la console : pas de questions tapées qui traînent
        pass

    def finish(self):
        super().finish()
        self.server.application.index.fermer()  # ferme la connexion SQLite de ce fil

    # -- contrôles

    def _controler(self, api: bool) -> None:
        port = self.server.server_address[1]
        if self.client_address[0] != "127.0.0.1":
            raise Refus(403, "Fouine ne répond qu'à ce PC.")
        if self.headers.get("Host", "").lower() not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            raise Refus(403, "Adresse refusée.")
        origine = self.headers.get("Origin")
        if origine is not None and origine.lower() not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
            raise Refus(403, "Demande venue d'un autre site : refusée.")
        if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
            raise Refus(403, "Demande venue d'un autre site : refusée.")
        if api:
            jeton = self.headers.get("X-Fouine-Jeton", "")
            if not hmac.compare_digest(jeton.encode(), self.server.jeton.encode()):
                raise Refus(403, "Jeton manquant. Relancez Fouine et utilisez la page qui s'ouvre.")

    def _repondre(self, code: int, corps: bytes, type_contenu: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", type_contenu)
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Content-Security-Policy", _SECURITE)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corps)

    def _json(self, code: int, donnees: dict) -> None:
        self._repondre(code, json.dumps(donnees, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _refuser(self, refus: Refus) -> None:
        self.close_connection = True
        self._json(refus.code, {"erreur": refus.message})

    # -- méthodes

    def do_GET(self):
        chemin = self.path.split("?", 1)[0]
        try:
            if chemin == "/api/etat":
                self._controler(api=True)
                return self._json(200, self.server.application.etat())
            if chemin == "/api/vignette":
                self._controler(api=True)
                demande = parse_qs(self.path.partition("?")[2]).get("id", [""])
                return self._repondre(200, self.server.application.vignette(demande[0]), "image/jpeg")
            self._controler(api=False)
            if chemin not in _STATIQUES:
                raise Refus(404, "Page introuvable.")
            nom, type_contenu = _STATIQUES[chemin]
            self._repondre(200, (DOSSIER_WEB / nom).read_bytes(), type_contenu)
        except Refus as refus:
            self._refuser(refus)
        except Exception as erreur:
            self._refuser(Refus(500, f"Erreur inattendue ({type(erreur).__name__})."))

    do_HEAD = do_GET

    def do_POST(self):
        chemin = self.path.split("?", 1)[0]
        try:
            self._controler(api=True)
            action = Application.ACTIONS.get(chemin[len("/api/"):]) if chemin.startswith("/api/") else None
            if action is None:
                raise Refus(404, "Action inconnue.")
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                raise Refus(415, "Format refusé.")
            try:
                longueur = int(self.headers.get("Content-Length", ""))
            except ValueError:
                raise Refus(411, "Longueur manquante.") from None
            if not 0 <= longueur <= _CORPS_MAX:
                raise Refus(413, "Demande trop longue.")
            try:
                corps = json.loads(self.rfile.read(longueur) or b"{}")
            except ValueError:
                raise Refus(400, "Demande illisible.") from None
            if not isinstance(corps, dict):
                raise Refus(400, "Demande illisible.")
            self._json(200, action(self.server.application, corps))
        except Refus as refus:
            self._refuser(refus)
        except Exception as erreur:
            self._refuser(Refus(500, f"Erreur inattendue ({type(erreur).__name__})."))

    def _interdit(self):
        self._refuser(Refus(405, "Méthode refusée."))

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _interdit


class Serveur(ThreadingHTTPServer):
    daemon_threads = True
    # Sous Windows, cette option laisserait un autre programme écouter sur le même port.
    allow_reuse_address = False

    def __init__(self, application: Application, port: int = 0):
        super().__init__(("127.0.0.1", port), Gestionnaire)
        self.application = application
        self.jeton = secrets.token_urlsafe(32)

    @property
    def adresse(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/"

    @property
    def adresse_complete(self) -> str:
        """L'adresse à ouvrir : le jeton suit le « # », il n'est donc jamais envoyé sur le réseau."""
        return f"{self.adresse}#{self.jeton}"
