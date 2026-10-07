"""Lecture du texte des fichiers : texte simple, pages web, PDF, Word, PowerPoint, Excel, LibreOffice.

Les documents Office sont des archives zip contenant du XML : ils sont lus avec
la bibliothèque standard, sans logiciel supplémentaire.
"""

from __future__ import annotations

import logging
import os
import re
import zipfile
from html.parser import HTMLParser
from xml.etree import ElementTree

# Au-delà, le texte d'un fichier est coupé (environ 400 pages).
TEXTE_MAX = 1_000_000
# Taille maximale d'un élément décompressé dans un document Office.
_XML_MAX = 50 * 1024 * 1024

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_ODF_TEXTE = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


class Illisible(Exception):
    """Le fichier n'a pas pu être lu ; le message explique pourquoi, en mots simples."""


def extraire(chemin: str) -> str:
    """Rend le texte d'un fichier. Lève `Illisible` si ce n'est pas possible."""
    ext = os.path.splitext(chemin)[1].lower()
    try:
        if ext == ".pdf":
            texte = _pdf(chemin)
        elif ext == ".docx":
            texte = _docx(chemin)
        elif ext == ".pptx":
            texte = _pptx(chemin)
        elif ext == ".xlsx":
            texte = _xlsx(chemin)
        elif ext in (".odt", ".odp", ".ods"):
            texte = _odf(chemin)
        elif ext in (".html", ".htm"):
            texte = _html(_texte_brut(chemin))
        else:
            texte = _texte_brut(chemin)
    except Illisible:
        raise
    except PermissionError:
        raise Illisible("Accès refusé") from None
    except FileNotFoundError:
        raise Illisible("Fichier introuvable") from None
    except (zipfile.BadZipFile, ElementTree.ParseError, KeyError):
        raise Illisible("Document abîmé ou dans un format inattendu") from None
    except Exception as erreur:  # un fichier bizarre ne doit jamais arrêter l'indexation
        raise Illisible(f"Lecture impossible ({type(erreur).__name__})") from None
    return _nettoyer(texte)[:TEXTE_MAX]


def _nettoyer(texte: str) -> str:
    texte = texte.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    texte = re.sub(r"[ \t\f\v ]+", " ", texte)
    texte = re.sub(r" ?\n ?", "\n", texte)
    return re.sub(r"\n{3,}", "\n\n", texte).strip()


def _texte_brut(chemin: str) -> str:
    with open(chemin, "rb") as fichier:
        donnees = fichier.read(TEXTE_MAX * 4)
    if donnees[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return donnees.decode("utf-16", errors="replace")
    if b"\x00" in donnees[:8192]:
        raise Illisible("Ce n'est pas un fichier de texte")
    try:
        return donnees.decode("utf-8-sig")
    except UnicodeDecodeError:
        return donnees.decode("cp1252", errors="replace")


class _LecteurHTML(HTMLParser):
    _IGNORES = {"script", "style", "noscript", "template", "svg", "head"}
    _BLOCS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.morceaux: list[str] = []
        self._ignore = 0
        self.titre = ""
        self._dans_titre = False

    def handle_starttag(self, balise, attributs):
        if balise == "title":
            self._dans_titre = True
        elif balise in self._IGNORES:
            self._ignore += 1
        if balise in self._BLOCS:
            self.morceaux.append("\n")

    def handle_endtag(self, balise):
        if balise == "title":
            self._dans_titre = False
        elif balise in self._IGNORES and self._ignore:
            self._ignore -= 1
        if balise in self._BLOCS:
            self.morceaux.append("\n")

    def handle_data(self, donnees):
        if self._dans_titre:
            self.titre += donnees
        elif not self._ignore:
            self.morceaux.append(donnees)


def _html(source: str) -> str:
    lecteur = _LecteurHTML()
    lecteur.feed(source)
    lecteur.close()
    return (lecteur.titre.strip() + "\n\n" + "".join(lecteur.morceaux)).strip()


def _pdf(chemin: str) -> str:
    from pypdf import PdfReader

    logging.getLogger("pypdf").setLevel(logging.CRITICAL)  # pas de messages techniques dans la console
    lecteur = PdfReader(chemin)
    if lecteur.is_encrypted:
        try:
            ouvert = lecteur.decrypt("")
        except Exception:
            ouvert = 0
        if not ouvert:
            raise Illisible("PDF protégé par un mot de passe")
    pages: list[str] = []
    total = 0
    for page in lecteur.pages:
        try:
            texte = page.extract_text() or ""
        except Exception:
            texte = ""
        pages.append(texte)
        total += len(texte)
        if total > TEXTE_MAX:
            break
    return "\n\n".join(pages)


def _xml(archive: zipfile.ZipFile, nom: str) -> ElementTree.Element:
    infos = archive.getinfo(nom)
    if infos.file_size > _XML_MAX:
        raise Illisible("Document trop volumineux une fois décompressé")
    donnees = archive.read(nom)
    if b"<!ENTITY" in donnees or b"<!DOCTYPE" in donnees:
        raise Illisible("Document au contenu inhabituel, non lu par prudence")
    return ElementTree.fromstring(donnees)


def _numero(nom: str) -> int:
    chiffres = re.findall(r"\d+", os.path.basename(nom))
    return int(chiffres[-1]) if chiffres else 0


def _docx(chemin: str) -> str:
    with zipfile.ZipFile(chemin) as archive:
        noms = ["word/document.xml"] + sorted(
            n for n in archive.namelist() if re.fullmatch(r"word/(footnotes|endnotes)\.xml", n)
        )
        paragraphes: list[str] = []
        for nom in noms:
            for paragraphe in _xml(archive, nom).iter(_W + "p"):
                morceaux = []
                for element in paragraphe.iter():
                    if element.tag == _W + "t":
                        morceaux.append(element.text or "")
                    elif element.tag in (_W + "tab", _W + "br"):
                        morceaux.append(" ")
                paragraphes.append("".join(morceaux))
    return "\n".join(paragraphes)


def _pptx(chemin: str) -> str:
    with zipfile.ZipFile(chemin) as archive:
        diapos = sorted(
            (n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=_numero
        )
        notes = sorted(
            (n for n in archive.namelist() if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", n)),
            key=_numero,
        )
        blocs: list[str] = []
        for nom in diapos + notes:
            lignes = []
            for paragraphe in _xml(archive, nom).iter(_A + "p"):
                ligne = "".join(t.text or "" for t in paragraphe.iter(_A + "t"))
                if ligne.strip():
                    lignes.append(ligne)
            blocs.append("\n".join(lignes))
    return "\n\n".join(blocs)


def _xlsx(chemin: str) -> str:
    """Texte des cellules d'un classeur (les nombres seuls ne sont pas gardés)."""
    with zipfile.ZipFile(chemin) as archive:
        noms = archive.namelist()
        lignes: list[str] = []
        if "xl/workbook.xml" in noms:
            for feuille in _xml(archive, "xl/workbook.xml").iter(_S + "sheet"):
                if feuille.get("name"):
                    lignes.append(feuille.get("name"))
        if "xl/sharedStrings.xml" in noms:
            for chaine in _xml(archive, "xl/sharedStrings.xml").iter(_S + "si"):
                texte = "".join(t.text or "" for t in chaine.iter(_S + "t"))
                if texte.strip():
                    lignes.append(texte)
        for nom in sorted((n for n in noms if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)), key=_numero):
            for cellule in _xml(archive, nom).iter(_S + "is"):
                texte = "".join(t.text or "" for t in cellule.iter(_S + "t"))
                if texte.strip():
                    lignes.append(texte)
    return "\n".join(lignes)


def _odf(chemin: str) -> str:
    with zipfile.ZipFile(chemin) as archive:
        racine = _xml(archive, "content.xml")
    lignes = []
    for element in racine.iter():
        if element.tag in (_ODF_TEXTE + "p", _ODF_TEXTE + "h"):
            ligne = "".join(element.itertext())
            if ligne.strip():
                lignes.append(ligne)
    return "\n".join(lignes)


def decouper(texte: str, taille: int = 700, recouvrement: int = 120) -> list[str]:
    """Coupe un texte en morceaux qui se chevauchent un peu.

    La coupe se fait de préférence à une fin de paragraphe, de phrase ou de mot,
    pour ne pas trancher une idée en deux.
    """
    texte = texte.strip()
    if not texte:
        return []
    morceaux: list[str] = []
    debut = 0
    while debut < len(texte):
        fin = min(debut + taille, len(texte))
        if fin < len(texte):
            minimum = debut + taille // 2
            for separateur in ("\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " "):
                position = texte.rfind(separateur, minimum, fin)
                if position != -1:
                    fin = position + len(separateur)
                    break
        morceau = texte[debut:fin].strip()
        if morceau:
            morceaux.append(morceau)
        if fin >= len(texte):
            break
        suivant = fin - recouvrement
        # Reprendre au début d'un mot plutôt qu'au milieu.
        espace = texte.find(" ", suivant, fin)
        debut = max(espace + 1 if espace != -1 else suivant, debut + 1)
    return morceaux
