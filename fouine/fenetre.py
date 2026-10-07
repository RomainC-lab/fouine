"""La fenêtre de Fouine : la même page que dans le navigateur, dans une fenêtre à elle.

La page vient toujours du serveur local (`serveur.py`), avec le même jeton et les mêmes
contrôles. La fenêtre est affichée par pywebview : WebView2 sous Windows (le moteur de
Edge, déjà présent sur Windows 11), WebKitGTK sous Linux, WebKit sous macOS.

Aucune fonction Python n'est offerte à la page (pas de `js_api`) : elle ne parle à Fouine
que par le serveur local, comme avant.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import reglages as mod_reglages
from .journal import journal

TITRE = "Fouine"
LARGEUR, HAUTEUR = 1100, 720  # tient sur un écran de portable de 1366 × 768
TAILLE_MIN = (720, 520)
_FONDS = {"light": "#e9ece4", "dark": "#0e1613"}  # les mêmes que dans style.css
# La page doit s'afficher dans ce délai ; sinon Fouine se rabat sur le navigateur.
DELAI_PAGE = 45
QUESTION_FERMETURE = (
    "Une indexation est en cours.\n\nFermer Fouine quand même ? Ce qui est déjà lu est gardé, "
    "et l'indexation reprendra où elle en était quand vous la relancerez."
)


class Indisponible(Exception):
    """La fenêtre ne peut pas s'afficher sur ce PC ; le message dit pourquoi, en clair."""


def _icone() -> str | None:
    embarque = getattr(sys, "_MEIPASS", None)
    for dossier in ([Path(embarque) / "fouine"] if embarque else []) + [Path(__file__).parent]:
        if (dossier / "icone.png").is_file():
            return str(dossier / "icone.png")
    return None


def verifier() -> None:
    """Lève `Indisponible` si la fenêtre ne peut pas s'afficher, sans rien ouvrir."""
    try:
        import webview  # noqa: F401
    except Exception as erreur:
        raise Indisponible("la bibliothèque pywebview n'est pas installée") from erreur
    if sys.platform == "win32":
        try:
            from webview.platforms import winforms
        except Exception as erreur:
            raise Indisponible(f"le module .NET n'a pas pu être chargé ({type(erreur).__name__})") from erreur
        if not winforms.is_chromium:
            raise Indisponible("le composant WebView2 de Microsoft Edge n'est pas installé sur ce PC")
    elif sys.platform != "darwin":
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            raise Indisponible("pas d'écran graphique")
        try:
            import gi

            gi.require_version("Gtk", "3.0")
            try:
                gi.require_version("WebKit2", "4.1")
            except ValueError:
                gi.require_version("WebKit2", "4.0")
        except Exception as erreur:
            try:
                import qtpy  # noqa: F401
            except Exception:
                raise Indisponible("ni WebKitGTK (PyGObject) ni Qt ne sont installés") from erreur


def _fenetres_windows() -> list[dict]:
    """Les fenêtres visibles de ce programme, vues par Windows (titre et taille)."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    trouvees = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def voir(poignee, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(poignee, ctypes.byref(pid))
        if pid.value == os.getpid() and user32.IsWindowVisible(poignee):
            titre = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(poignee, titre, 256)
            cadre = wintypes.RECT()
            user32.GetWindowRect(poignee, ctypes.byref(cadre))
            trouvees.append({"poignee": poignee, "titre": titre.value,
                             "largeur": cadre.right - cadre.left, "hauteur": cadre.bottom - cadre.top})
        return True

    user32.EnumWindows(voir, 0)
    return trouvees


def _premier_plan(fenetre) -> None:
    """Ramène la fenêtre devant les autres (demandé par un second lancement de Fouine)."""
    try:
        fenetre.restore()
        fenetre.show()
        if sys.platform == "win32":
            import ctypes

            for trouvee in _fenetres_windows():
                if trouvee["titre"] == TITRE:
                    ctypes.windll.user32.SetForegroundWindow(trouvee["poignee"])
        else:
            fenetre.on_top = True
            fenetre.on_top = False
    except Exception as erreur:  # une fenêtre qui se ferme au même moment, par exemple
        journal.warning("La fenêtre n'a pas pu être ramenée devant : %s", erreur)


def ouvrir(serveur, essai=None) -> None:
    """Affiche la fenêtre et ne rend la main que lorsqu'elle est fermée.

    Lève `Indisponible` si la page ne s'est pas affichée (la fenêtre est alors refermée).
    `essai` : fonction appelée avec la fenêtre une fois la page affichée (essai automatique)."""
    verifier()
    import webview

    application = serveur.application
    webview.settings["ALLOW_DOWNLOADS"] = False
    webview.settings["ALLOW_FILE_URLS"] = False
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    theme = mod_reglages.charger_theme(application.dossier)
    fenetre = webview.create_window(
        TITRE, serveur.adresse_complete, width=LARGEUR, height=HAUTEUR, min_size=TAILLE_MIN,
        text_select=True,  # pour pouvoir copier un extrait ou un chemin
        background_color=_FONDS.get(theme, "#e9ece4"),
    )
    etat = {"affichee": False, "abandon": None}

    def avant_fermeture():
        # pywebview pose lui-même la question si `confirm_close` est vrai : on ne le met
        # à vrai que pendant une indexation.
        fenetre.confirm_close = bool(application.tache["en_cours"]) and etat["abandon"] is None and essai is None

    def surveiller():
        debut = time.monotonic()
        while not serveur.page_vivante.wait(0.2):
            if fenetre.events.closed.is_set():
                return
            if time.monotonic() - debut > DELAI_PAGE:
                etat["abandon"] = "la page ne s'est pas affichée dans la fenêtre"
                fenetre.destroy()
                return
        etat["affichee"] = True
        journal.info("Fenêtre ouverte, page affichée.")
        if essai is not None:
            try:
                essai(fenetre)
            finally:
                fenetre.destroy()

    fenetre.events.closing += avant_fermeture
    serveur.premier_plan = lambda: _premier_plan(fenetre)
    options = {"localization": {"global.quitConfirmation": QUESTION_FERMETURE, "global.cancel": "Annuler"}}
    if sys.platform == "win32":
        options["gui"] = "edgechromium"
    elif _icone():
        options["icon"] = _icone()
    try:
        webview.start(surveiller, **options)
    except Exception as erreur:
        raise Indisponible(f"la fenêtre n'a pas pu s'ouvrir ({type(erreur).__name__} : {erreur})") from erreur
    finally:
        serveur.premier_plan = None
    if etat["abandon"]:
        raise Indisponible(etat["abandon"])
    if not etat["affichee"] and not serveur.page_vivante.is_set():
        raise Indisponible("la fenêtre s'est refermée avant d'afficher la page")


# ---------------------------------------------------------------- essai automatique

def essai_automatique(serveur, dossier: Path, capture: str | None, rapport: list[str]):
    """Fabrique la fonction d'essai passée à `ouvrir` (option cachée `--essai-fenetre`).

    Elle vérifie, dans la vraie fenêtre : le titre, un élément de l'interface, que le script de
    la page a parlé au serveur avec le bon jeton, et qu'un second lancement de Fouine ne démarre
    pas un second serveur mais réveille celui-ci. Chaque constat est ajouté à `rapport` ; une
    ligne qui commence par « RATÉ » fait échouer l'essai."""

    def noter(ok: bool, texte: str) -> None:
        rapport.append(("  ok  " if ok else "RATÉ  ") + texte)
        journal.info(rapport[-1])

    def essai(fenetre) -> None:
        import webview

        noter(fenetre.events.loaded.wait(30), "la fenêtre annonce que la page est chargée")
        try:
            moteur = webview.renderer
        except AttributeError:
            moteur = "?"
        noter(True, f"moteur d'affichage : {moteur}")
        try:
            # Script confié tel quel au moteur de la fenêtre. La fonction `evaluate_js` habituelle de
            # pywebview passe par `eval`, que la page de Fouine interdit (règle « script-src 'self' »).
            lu = fenetre.gui.evaluate_js(
                "JSON.stringify([document.title, !!document.getElementById('question'), "
                "(document.querySelector('header h1') || {}).textContent || null, "
                "!!document.getElementById('theme'), location.hostname, "
                "(document.getElementById('version') || {}).textContent || null])",
                fenetre.uid, True,
            )
            attendu = [TITRE, True, "Fouine", True, "127.0.0.1"]
            noter(isinstance(lu, list) and lu[:5] == attendu,
                  f"lu dans la fenêtre (titre de la page, champ de recherche, « Fouine », bouton de thème, "
                  f"adresse, version) : {lu!r}")
        except Exception as erreur:
            noter(False, f"lecture de la page par pywebview : {type(erreur).__name__} : {erreur}")
        noter(serveur.page_vivante.is_set(), "le script de la page a interrogé le serveur avec le bon jeton")
        if sys.platform == "win32":
            vues = [f for f in _fenetres_windows() if f["titre"] == TITRE]
            noter(bool(vues), "Windows voit une fenêtre visible intitulée « Fouine » : "
                  + ", ".join(f"{f['largeur']} × {f['hauteur']}" for f in vues))
        if capture:
            try:
                from PIL import ImageGrab

                time.sleep(2.5)  # le temps que l'image soit dessinée
                ImageGrab.grab().save(capture)
                noter(True, f"capture d'écran enregistrée : {Path(capture).name}")
            except Exception as erreur:
                noter(True, f"(pas de capture d'écran : {type(erreur).__name__} : {erreur})")
        # Second lancement, sur le même dossier de données : il doit s'arrêter tout seul.
        commande = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "fouine"]
        try:
            second = subprocess.run(commande + ["--donnees", str(dossier)], timeout=60, capture_output=True,
                                    stdin=subprocess.DEVNULL)
            noter(second.returncode == 0 and serveur.reveils == 1,
                  f"second lancement : s'arrête (code {second.returncode}) et réveille le premier "
                  f"({serveur.reveils} demande reçue)")
        except Exception as erreur:
            noter(False, f"second lancement : {type(erreur).__name__} : {erreur}")

    return essai
