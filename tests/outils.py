"""Outils communs aux tests : faux modèles, fabrication de documents et d'images."""

from __future__ import annotations

import zipfile

from fouine.factice import FauxEmbedding, FauxEmbeddingImages  # noqa: F401 - repris par les tests
from fouine.reglages import reglages_par_defaut


def reglages_pour(*dossiers, **changements) -> dict:
    reglages = reglages_par_defaut()
    reglages["dossiers"] = [str(d) for d in dossiers]
    reglages.update(changements)
    return reglages


def ecrire(chemin, contenu="bonjour", encodage="utf-8"):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(contenu, bytes):
        chemin.write_bytes(contenu)
    else:
        chemin.write_text(contenu, encoding=encodage)
    return chemin


def _zip(chemin, fichiers: dict):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(chemin, "w", zipfile.ZIP_DEFLATED) as archive:
        for nom, contenu in fichiers.items():
            archive.writestr(nom, contenu)
    return chemin


def docx(chemin, paragraphes):
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    corps = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphes)
    return _zip(chemin, {"word/document.xml": f'<?xml version="1.0"?><w:document xmlns:w="{w}"><w:body>{corps}</w:body></w:document>'})


def pptx(chemin, diapos):
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    p = "http://schemas.openxmlformats.org/presentationml/2006/main"
    fichiers = {}
    for numero, lignes in enumerate(diapos, start=1):
        corps = "".join(f"<a:p><a:r><a:t>{ligne}</a:t></a:r></a:p>" for ligne in lignes)
        fichiers[f"ppt/slides/slide{numero}.xml"] = (
            f'<?xml version="1.0"?><p:sld xmlns:p="{p}" xmlns:a="{a}"><p:cSld><p:spTree><p:sp><p:txBody>'
            f"{corps}</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
        )
    return _zip(chemin, fichiers)


def xlsx(chemin, textes, feuille="Budget"):
    s = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    chaines = "".join(f"<si><t>{t}</t></si>" for t in textes)
    return _zip(chemin, {
        "xl/workbook.xml": f'<?xml version="1.0"?><workbook xmlns="{s}"><sheets><sheet name="{feuille}" sheetId="1"/></sheets></workbook>',
        "xl/sharedStrings.xml": f'<?xml version="1.0"?><sst xmlns="{s}">{chaines}</sst>',
    })


def odt(chemin, paragraphes):
    office = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    text = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    corps = "".join(f"<text:p>{p}</text:p>" for p in paragraphes)
    return _zip(chemin, {"content.xml": (
        f'<?xml version="1.0"?><office:document-content xmlns:office="{office}" xmlns:text="{text}">'
        f"<office:body><office:text>{corps}</office:text></office:body></office:document-content>"
    )})


def pdf(chemin, lignes):
    """Un PDF minimal d'une page, écrit à la main (texte sans accents)."""
    contenu = "BT /F1 12 Tf 72 720 Td 16 TL " + " ".join(
        "(" + ligne.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj T*" for ligne in lignes
    ) + " ET"
    objets = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(contenu)} >>\nstream\n{contenu}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    sortie = b"%PDF-1.4\n"
    positions = []
    for numero, objet in enumerate(objets, start=1):
        positions.append(len(sortie))
        sortie += f"{numero} 0 obj\n{objet}\nendobj\n".encode("latin-1")
    debut_table = len(sortie)
    sortie += f"xref\n0 {len(objets) + 1}\n0000000000 65535 f \n".encode()
    for position in positions:
        sortie += f"{position:010d} 00000 n \n".encode()
    sortie += f"trailer\n<< /Size {len(objets) + 1} /Root 1 0 R >>\nstartxref\n{debut_table}\n%%EOF\n".encode()
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(sortie)
    return chemin


def image(chemin, couleur=(200, 30, 30), taille=(320, 240), **options):
    """Une image d'une seule couleur, au format donné par l'extension du fichier."""
    from PIL import Image

    chemin.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", taille, couleur).save(chemin, **options)
    return chemin
