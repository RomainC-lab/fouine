"""Réglages de Fouine : où sont rangées les données, et quels filtres s'appliquent.

Les réglages sont gardés dans un fichier `reglages.json` lisible, que l'on peut
modifier à la main ou depuis l'interface.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

NOM_FICHIER = "reglages.json"

# Dossiers du système : jamais utiles pour retrouver un document personnel.
DOSSIERS_SYSTEME = [
    "Windows",
    "Program Files",
    "Program Files (x86)",
    "ProgramData",
    "AppData",
    "$Recycle.Bin",
    "System Volume Information",
    "Recovery",
    "$WinREAgent",
    "lost+found",
]

# Dossiers techniques : du code, des caches, rien d'écrit par une personne.
DOSSIERS_TECHNIQUES = [
    ".git",
    ".svn",
    ".hg",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    "site-packages",
    "cache",
    "caches",
    ".cache",
    ".idea",
    ".vscode",
]

# Seuls ces types de documents sont lus. Tout le reste (vidéos, musique,
# archives, programmes…) est écarté sans être ouvert. Les images ont leur
# propre liste, plus bas.
EXTENSIONS = [
    ".txt",
    ".md",
    ".rst",
    ".csv",
    ".tsv",
    ".html",
    ".htm",
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".odt",
    ".odp",
    ".ods",
]

# Fichiers et dossiers sensibles : jamais lus. Les motifs sont comparés au nom
# (sans tenir compte des majuscules) ; « * » remplace n'importe quelle suite.
MOTIFS_SENSIBLES = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.pfx",
    "*.p12",
    "*.ppk",
    "*.kdbx",
    "*.kdb",
    "*.keystore",
    "*.jks",
    "*.gpg",
    "*.asc",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    "wallet.dat",
    "*.wallet",
    "*wallet*",
    "*portefeuille*",
    "*password*",
    "*passwd*",
    "*mot de passe*",
    "*mots de passe*",
    "*mot_de_passe*",
    "*mot-de-passe*",
    "*motdepasse*",
    "*mdp*",
    "*secret*",
    "*credential*",
    "*identifiants*",
    ".ssh",
    ".gnupg",
    ".aws",
    ".azure",
    ".kube",
    ".docker",
    ".password-store",
    ".netrc",
    ".npmrc",
    ".pypirc",
]

# Suites de dossiers qui désignent un profil de navigateur, de messagerie ou un
# coffre de mots de passe (historique, mots de passe enregistrés, cookies).
# « google/chrome » veut dire : un dossier « chrome » dans un dossier « google ».
CHEMINS_SENSIBLES = [
    "google/chrome",
    "google-chrome",
    ".config/chromium",
    "chromium/user data",
    "bravesoftware",
    "microsoft/edge",
    "mozilla/firefox",
    ".mozilla",
    "opera software",
    "vivaldi/user data",
    ".thunderbird",
    "thunderbird/profiles",
    "library/safari",
    "1password",
    "bitwarden",
    ".electrum",
]

TAILLE_MAX_MO = 20

# Images, lues seulement si l'option « Lire aussi les images » est cochée :
# les types que Pillow ouvre sans greffon.
EXTENSIONS_IMAGES = [".jpg", ".jpeg", ".jfif", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"]
IMAGE_COTE_MIN_PX = 64  # en dessous : icônes, miniatures, puces de pages web
IMAGE_TAILLE_MAX_MO = 40


def dossier_donnees() -> Path:
    """Dossier où Fouine range son index, ses réglages et le modèle."""
    force = os.environ.get("FOUINE_DONNEES")
    if force:
        return Path(force)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Fouine"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Fouine"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "fouine"


def dossiers_proposes() -> list[str]:
    """Documents, Bureau et Téléchargements, s'ils existent sur ce PC."""
    maison = Path.home()
    candidats = [
        ["Documents"],
        ["Desktop", "Bureau"],
        ["Downloads", "Téléchargements"],
    ]
    trouves: list[str] = []
    racines = [maison]
    for variable in ("OneDrive", "OneDriveConsumer"):
        valeur = os.environ.get(variable)
        if valeur:
            racines.append(Path(valeur))
    for noms in candidats:
        for racine in racines:
            for nom in noms:
                chemin = racine / nom
                if chemin.is_dir() and str(chemin) not in trouves:
                    trouves.append(str(chemin))
    return trouves


def reglages_par_defaut() -> dict:
    return {
        "dossiers": [],
        "dossiers_exclus": DOSSIERS_SYSTEME + DOSSIERS_TECHNIQUES,
        "inclure_caches": False,
        "extensions": list(EXTENSIONS),
        "taille_max_mo": TAILLE_MAX_MO,
        "lire_images": False,
        "image_cote_min_px": IMAGE_COTE_MIN_PX,
        "image_taille_max_mo": IMAGE_TAILLE_MAX_MO,
        "motifs_sensibles": list(MOTIFS_SENSIBLES),
        "chemins_sensibles": list(CHEMINS_SENSIBLES),
    }


def _liste_de_textes(valeur, defaut: list[str], maximum: int = 500) -> list[str]:
    if not isinstance(valeur, list):
        return list(defaut)
    propre: list[str] = []
    for element in valeur[:maximum]:
        if isinstance(element, str):
            element = element.strip()
            if element and len(element) <= 1000 and element not in propre:
                propre.append(element)
    return propre


def nettoyer(brut) -> dict:
    """Rend des réglages complets et valides à partir de ce qui a été reçu."""
    defaut = reglages_par_defaut()
    if not isinstance(brut, dict):
        return defaut
    propre = {
        "dossiers": _liste_de_textes(brut.get("dossiers"), []),
        "dossiers_exclus": _liste_de_textes(brut.get("dossiers_exclus"), defaut["dossiers_exclus"]),
        "inclure_caches": brut.get("inclure_caches") is True,
        "motifs_sensibles": _liste_de_textes(brut.get("motifs_sensibles"), defaut["motifs_sensibles"]),
        "chemins_sensibles": _liste_de_textes(brut.get("chemins_sensibles"), defaut["chemins_sensibles"]),
    }
    extensions = []
    for ext in _liste_de_textes(brut.get("extensions"), defaut["extensions"]):
        ext = ext.lower().lstrip("*")
        if not ext.startswith("."):
            ext = "." + ext
        if len(ext) > 1 and "/" not in ext and "\\" not in ext and ext not in extensions:
            extensions.append(ext)
    propre["extensions"] = extensions
    propre["taille_max_mo"] = _nombre(brut, "taille_max_mo", defaut, 2000)
    propre["lire_images"] = brut.get("lire_images") is True
    propre["image_cote_min_px"] = int(_nombre(brut, "image_cote_min_px", defaut, 10000))
    propre["image_taille_max_mo"] = _nombre(brut, "image_taille_max_mo", defaut, 2000)
    return propre


def _nombre(brut: dict, cle: str, defaut: dict, maximum: float):
    valeur = brut.get(cle, defaut[cle])
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)) or not (0 < valeur <= maximum):
        return defaut[cle]
    return valeur


def charger(dossier: Path | None = None) -> dict:
    """Lit les réglages ; au tout premier lancement, propose les dossiers habituels."""
    dossier = dossier or dossier_donnees()
    fichier = dossier / NOM_FICHIER
    try:
        return nettoyer(json.loads(fichier.read_text(encoding="utf-8")))
    except FileNotFoundError:
        reglages = reglages_par_defaut()
        reglages["dossiers"] = dossiers_proposes()
        return reglages
    except (OSError, ValueError):
        # Fichier abîmé : on repart des réglages par défaut, sans dossier choisi.
        return reglages_par_defaut()


def enregistrer(reglages: dict, dossier: Path | None = None) -> dict:
    dossier = dossier or dossier_donnees()
    dossier.mkdir(parents=True, exist_ok=True)
    propre = nettoyer(reglages)
    fichier = dossier / NOM_FICHIER
    provisoire = fichier.with_suffix(".json.tmp")
    provisoire.write_text(json.dumps(propre, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(provisoire, fichier)
    return propre
