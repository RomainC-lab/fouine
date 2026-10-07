"""Les filtres : quels fichiers Fouine a le droit de lire, et pourquoi pas les autres.

Une seule fonction parcourt les dossiers choisis (`parcourir`) ; l'aperçu et
l'indexation s'en servent toutes les deux, pour que l'aperçu montre exactement
ce qui sera lu.
"""

from __future__ import annotations

import fnmatch
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .reglages import DOSSIERS_SYSTEME, EXTENSIONS_IMAGES

# Raisons d'écarter un fichier ou un dossier (textes montrés tels quels).
SENSIBLE = "Fichier ou dossier sensible"
SYSTEME = "Dossier du système"
TECHNIQUE = "Dossier technique ou exclu"
CACHE = "Caché"
LIEN = "Raccourci (lien)"
TYPE = "Type de fichier non lu"
TROP_GROS = "Trop gros"
IMAGE_PETITE = "Image trop petite (icône, miniature)"
IMAGE_GEANTE = "Image trop grande"
ILLISIBLE = "Accès refusé"

# Dossiers du système repérés par leur emplacement exact (Linux, macOS).
_RACINES_SYSTEME = [
    "/proc", "/sys", "/dev", "/run", "/boot", "/etc", "/usr", "/var", "/bin",
    "/sbin", "/lib", "/lib32", "/lib64", "/opt", "/snap", "/root", "/tmp",
    "/System", "/Library", "/Applications", "/private", "/cores",
]

_ATTRIBUT_CACHE = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0x2)
_ATTRIBUT_SYSTEME = getattr(stat, "FILE_ATTRIBUTE_SYSTEM", 0x4)
_ATTRIBUT_RENVOI = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


@dataclass
class Element:
    """Un fichier ou un dossier rencontré pendant le parcours."""

    chemin: str
    raison: str | None  # None : le fichier est accepté
    est_dossier: bool = False
    taille: int = 0
    modifie: int = 0  # date de modification, en nanosecondes
    image: bool = False  # vrai pour une image (lue par le second modèle)


class Filtres:
    """Les réglages, préparés pour répondre vite à « ce fichier, on le lit ? »."""

    def __init__(self, reglages: dict, dimensions_connues=None):
        """`dimensions_connues(chemin, taille, modifie)` rend (largeur, hauteur) pour une
        image déjà dans l'index et inchangée : son en-tête n'est alors pas relu."""
        self.exclus = {nom.lower() for nom in reglages["dossiers_exclus"]}
        self.systeme = {nom.lower() for nom in DOSSIERS_SYSTEME}
        self.inclure_caches = bool(reglages["inclure_caches"])
        self.extensions = {ext.lower() for ext in reglages["extensions"]}
        self.taille_max = int(float(reglages["taille_max_mo"]) * 1024 * 1024)
        self.images = set(EXTENSIONS_IMAGES) if reglages.get("lire_images") else set()
        self.image_taille_max = int(float(reglages.get("image_taille_max_mo", 40)) * 1024 * 1024)
        self.image_cote_min = int(reglages.get("image_cote_min_px", 64))
        self.dimensions_connues = dimensions_connues or (lambda chemin, taille, modifie: None)
        self.motifs = [motif.lower() for motif in reglages["motifs_sensibles"]]
        self.chemins = [
            _parties(chemin)
            for chemin in reglages["chemins_sensibles"]
        ]

    def nom_sensible(self, nom: str) -> bool:
        nom = nom.lower()
        return any(fnmatch.fnmatchcase(nom, motif) for motif in self.motifs)

    def suite_sensible(self, chemin: str) -> bool:
        """Vrai si le chemin passe par un profil de navigateur ou un coffre."""
        parties = _parties(chemin)
        for suite in self.chemins:
            n = len(suite)
            if n and any(parties[i:i + n] == suite for i in range(len(parties) - n + 1)):
                return True
        return False

    def sensible(self, entree: os.DirEntry) -> bool:
        return self.nom_sensible(entree.name) or self.suite_sensible(entree.path)

    def racine_sensible(self, racine: str) -> bool:
        """Un dossier choisi est refusé s'il est lui-même dans un endroit sensible."""
        maison = os.path.realpath(os.path.expanduser("~"))
        relatif = os.path.relpath(racine, maison) if _est_dans(racine, maison) else racine
        noms = [] if relatif == "." else _parties(relatif)
        return any(self.nom_sensible(nom) for nom in noms) or self.suite_sensible(racine)

    def raison_dossier(self, entree: os.DirEntry) -> str | None:
        nom = entree.name
        if _est_lien(entree):
            return LIEN
        if self.sensible(entree):
            return SENSIBLE
        if nom.lower() in self.exclus:
            return SYSTEME if nom.lower() in self.systeme else TECHNIQUE
        if _racine_systeme(entree.path):
            return SYSTEME
        if not self.inclure_caches and _est_cache(entree):
            return CACHE
        return None

    def raison_fichier(self, entree: os.DirEntry) -> tuple[str | None, os.stat_result | None]:
        # Un raccourci n'est jamais suivi : si sa cible est dans un dossier choisi,
        # elle est lue à son vrai emplacement ; sinon elle n'a pas à être lue.
        if _est_lien(entree):
            return LIEN, None
        if self.sensible(entree):
            return SENSIBLE, None
        if not self.inclure_caches and _est_cache(entree):
            return CACHE, None
        ext = os.path.splitext(entree.name)[1].lower()
        image = ext in self.images
        if not image and ext not in self.extensions:
            return TYPE, None
        try:
            infos = entree.stat(follow_symlinks=False)
        except OSError:
            return ILLISIBLE, None
        if not stat.S_ISREG(infos.st_mode):
            return TYPE, None
        if infos.st_size > (self.image_taille_max if image else self.taille_max):
            return TROP_GROS, infos
        if image:
            return self._raison_image(entree.path, infos), infos
        return None, infos

    def _raison_image(self, chemin: str, infos: os.stat_result) -> str | None:
        """Écarte les icônes et les images démesurées, d'après leur taille en points.

        Seul l'en-tête du fichier est lu. Une image dont l'en-tête est illisible
        est gardée : l'indexation la notera « pas pu être lue ».
        """
        from . import images

        taille = self.dimensions_connues(chemin, infos.st_size, infos.st_mtime_ns) or images.dimensions(chemin)
        if taille is None:
            return None
        largeur, hauteur = taille
        if min(largeur, hauteur) < self.image_cote_min:
            return IMAGE_PETITE
        if largeur * hauteur > images.PIXELS_MAX:
            return IMAGE_GEANTE
        return None


def _parties(chemin: str) -> list[str]:
    return [p for p in chemin.lower().replace("\\", "/").split("/") if p]


def _est_lien(entree: os.DirEntry) -> bool:
    if entree.is_symlink():
        return True
    if sys.platform == "win32":
        # Jonctions et autres renvois de Windows : traités comme des raccourcis.
        try:
            attributs = entree.stat(follow_symlinks=False).st_file_attributes
        except (OSError, AttributeError):
            return False
        return bool(attributs & _ATTRIBUT_RENVOI)
    return False


def _est_cache(entree: os.DirEntry) -> bool:
    if entree.name.startswith("."):
        return True
    if sys.platform == "win32":
        try:
            attributs = entree.stat(follow_symlinks=False).st_file_attributes
        except (OSError, AttributeError):
            return False
        return bool(attributs & (_ATTRIBUT_CACHE | _ATTRIBUT_SYSTEME))
    return False


def _racine_systeme(chemin: str) -> bool:
    if sys.platform == "win32":
        return False
    return chemin in _RACINES_SYSTEME


def _est_dans(chemin: str, racine: str) -> bool:
    chemin = os.path.normcase(chemin)
    racine = os.path.normcase(racine)
    try:
        return os.path.commonpath([chemin, racine]) == racine
    except ValueError:  # deux disques différents sous Windows
        return False


def racines_utiles(dossiers: list[str]) -> tuple[list[str], list[str]]:
    """Sépare les dossiers choisis en (présents, introuvables), sans doublon.

    Un dossier déjà contenu dans un autre dossier choisi n'est pas parcouru deux fois.
    """
    presents: list[str] = []
    absents: list[str] = []
    for dossier in dossiers:
        chemin = os.path.abspath(os.path.expanduser(dossier))
        if os.path.isdir(chemin):
            reel = os.path.realpath(chemin)
            if reel not in presents:
                presents.append(reel)
        elif chemin not in absents:
            absents.append(chemin)
    presents.sort(key=len)
    gardes: list[str] = []
    for chemin in presents:
        if not any(_est_dans(chemin, autre) for autre in gardes):
            gardes.append(chemin)
    return gardes, absents


def parcourir(reglages: dict, arret=None, dimensions_connues=None, dossier_fouine=None) -> Iterator[Element]:
    """Passe dans les dossiers choisis et dit, pour chaque chose vue, si elle est lue.

    Un dossier écarté n'est pas ouvert : il compte pour un seul élément.
    `dossier_fouine` est le dossier de données de Fouine (index, vignettes, modèles) :
    il n'est jamais lu, même s'il se trouve dans un dossier choisi.
    """
    chez_fouine = os.path.normcase(os.path.realpath(dossier_fouine)) if dossier_fouine else None
    filtres = Filtres(reglages, dimensions_connues)
    racines, _ = racines_utiles(reglages["dossiers"])
    for racine in racines:
        if filtres.racine_sensible(racine):
            yield Element(racine, SENSIBLE, est_dossier=True)
            continue
        pile = [racine]
        while pile:
            if arret is not None and arret():
                return
            dossier = pile.pop()
            try:
                with os.scandir(dossier) as entrees:
                    liste = sorted(entrees, key=lambda e: e.name.lower())
            except OSError:
                yield Element(dossier, ILLISIBLE, est_dossier=True)
                continue
            sous_dossiers = []
            for entree in liste:
                try:
                    est_dossier = entree.is_dir(follow_symlinks=False) or (
                        entree.is_symlink() and entree.is_dir()
                    )
                except OSError:
                    yield Element(entree.path, ILLISIBLE)
                    continue
                if est_dossier:
                    raison = filtres.raison_dossier(entree)
                    if raison is None and chez_fouine and os.path.normcase(os.path.realpath(entree.path)) == chez_fouine:
                        raison = TECHNIQUE
                    if raison:
                        yield Element(entree.path, raison, est_dossier=True)
                    else:
                        sous_dossiers.append(entree.path)
                    continue
                raison, infos = filtres.raison_fichier(entree)
                yield Element(
                    entree.path,
                    raison,
                    taille=infos.st_size if infos else 0,
                    modifie=infos.st_mtime_ns if infos else 0,
                    image=os.path.splitext(entree.name)[1].lower() in filtres.images,
                )
            pile.extend(reversed(sous_dossiers))


def apercu(reglages: dict, exemples: int = 5, dimensions_connues=None, deja_lu=None, dossier_fouine=None) -> dict:
    """Compte ce qui serait lu et ce qui serait écarté, raison par raison.

    `deja_lu(element)` dit si un fichier est déjà dans l'index, inchangé : cela
    permet de compter les images qui restent à lire (ce sont elles qui prennent du temps).
    """
    racines, absents = racines_utiles(reglages["dossiers"])
    acceptes = {"nombre": 0, "taille": 0, "exemples": [], "par_type": {}, "images": 0, "images_a_lire": 0}
    ecartes: dict[str, dict] = {}
    for element in parcourir(reglages, dimensions_connues=dimensions_connues, dossier_fouine=dossier_fouine):
        if element.raison is None:
            acceptes["nombre"] += 1
            if element.image:
                acceptes["images"] += 1
                if deja_lu is None or not deja_lu(element):
                    acceptes["images_a_lire"] += 1
            acceptes["taille"] += element.taille
            if len(acceptes["exemples"]) < exemples:
                acceptes["exemples"].append(element.chemin)
            ext = os.path.splitext(element.chemin)[1].lower()
            acceptes["par_type"][ext] = acceptes["par_type"].get(ext, 0) + 1
            continue
        groupe = ecartes.setdefault(
            element.raison, {"raison": element.raison, "fichiers": 0, "dossiers": 0, "exemples": []}
        )
        groupe["dossiers" if element.est_dossier else "fichiers"] += 1
        if len(groupe["exemples"]) < exemples:
            groupe["exemples"].append(element.chemin)
    return {
        "dossiers": racines,
        "introuvables": absents,
        "acceptes": acceptes,
        "ecartes": sorted(ecartes.values(), key=lambda g: -(g["fichiers"] + g["dossiers"])),
    }
