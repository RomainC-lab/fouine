"""Auto-test du programme : `Fouine.exe --autotest` (ou `python -m fouine --autotest`).

Sert à la chaîne qui fabrique le programme Windows : il vérifie, sans réseau et
sans toucher aux données de l'utilisateur, que tout ce qu'il faut est bien dans
le paquet. Les modèles sont remplacés par des faux ; les bibliothèques de calcul
sont tout de même essayées sur un modèle minuscule fabriqué sur place.
"""

from __future__ import annotations

import base64
import http.client
import io
import json
import tempfile
import threading
from pathlib import Path

# Un modèle ONNX de quelques octets : il rend le double du nombre reçu.
_MODELE_MINUSCULE = (
    "CAgSBmZvdWluZTo6Cg4KAXgKAXgSAXkiA0FkZBIGZm91aW5lWg8KAXgSCgoICAESBAoCCAFiDwoBeRIKCggIARIECgIIAUIECgAQDQ=="
)
_DECOUPEUR_MINUSCULE = json.dumps({
    "version": "1.0", "truncation": None, "padding": None, "added_tokens": [], "normalizer": None,
    "pre_tokenizer": {"type": "Whitespace"}, "post_processor": None, "decoder": None,
    "model": {"type": "WordLevel", "vocab": {"[inconnu]": 0, "bonjour": 1, "fouine": 2}, "unk_token": "[inconnu]"},
})


def _bibliotheques() -> list[str]:
    """Charge les bibliothèques de calcul et leur fait faire un vrai petit travail."""
    import numpy
    import onnxruntime
    import PIL
    import pypdf
    import tokenizers
    from fastembed import TextEmbedding
    from huggingface_hub import snapshot_download  # noqa: F401 - doit être dans le paquet

    session = onnxruntime.InferenceSession(base64.b64decode(_MODELE_MINUSCULE), providers=["CPUExecutionProvider"])
    double = session.run(None, {"x": numpy.array([21], dtype=numpy.float32)})[0]
    if float(double[0]) != 42.0:
        raise RuntimeError("le calcul ONNX ne rend pas le bon résultat")
    decoupeur = tokenizers.Tokenizer.from_str(_DECOUPEUR_MINUSCULE)
    if decoupeur.encode("bonjour fouine").ids != [1, 2]:
        raise RuntimeError("le découpage en jetons ne rend pas le bon résultat")
    connus = {modele["model"] for modele in TextEmbedding.list_supported_models()}
    from .embedding import MODELE

    if MODELE not in connus:
        raise RuntimeError("fastembed ne connaît pas le modèle des textes")
    return [
        f"numpy {numpy.__version__}", f"onnxruntime {onnxruntime.__version__}", f"tokenizers {tokenizers.__version__}",
        f"Pillow {PIL.__version__}", f"pypdf {pypdf.__version__}",
    ]


def lancer() -> int:
    """Rend 0 si tout marche. Chaque étape est écrite dans la console."""
    from PIL import Image

    from . import __version__, reglages as mod_reglages
    from .factice import FauxEmbedding, FauxEmbeddingImages
    from .index import Index
    from .serveur import DOSSIER_WEB, Application, Serveur

    def etape(texte):
        print("  ok  " + texte, flush=True)

    print(f"Auto-test de Fouine {__version__} (sans réseau, dans un dossier provisoire)", flush=True)
    etape("bibliothèques : " + ", ".join(_bibliotheques()))
    for nom in ("index.html", "app.js", "style.css"):
        if not (DOSSIER_WEB / nom).is_file():
            raise RuntimeError(f"fichier de l'interface manquant : {nom}")
    etape(f"interface présente dans {DOSSIER_WEB}")

    with tempfile.TemporaryDirectory(prefix="fouine-autotest-", ignore_cleanup_errors=True) as provisoire:
        base = Path(provisoire).resolve()
        documents, donnees = base / "Documents", base / "donnees"
        documents.mkdir()
        (documents / "Facture du plombier.txt").write_text(
            "Réparation de la fuite sous l'évier : 187 euros.", encoding="utf-8"
        )
        (documents / "Recette.md").write_text("Tarte aux pommes de grand-mère.", encoding="utf-8")
        Image.new("RGB", (320, 240), (210, 20, 20)).save(documents / "tomate.jpg")
        Image.new("RGB", (320, 240), (20, 30, 220)).save(documents / "mer.png")
        Image.new("RGB", (16, 16), (0, 0, 0)).save(documents / "icone.png")
        reglages = mod_reglages.reglages_par_defaut()
        reglages.update(dossiers=[str(documents)], lire_images=True)
        mod_reglages.enregistrer(reglages, donnees)

        index = Index(donnees, FauxEmbedding(), FauxEmbeddingImages())
        application = Application(index, donnees, ouvrir=lambda chemin, quoi: None)
        serveur = Serveur(application)
        port = serveur.server_address[1]
        fil = threading.Thread(target=serveur.serve_forever, daemon=True)
        fil.start()
        try:
            def demander(methode, chemin, corps=None):
                connexion = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
                entetes = {"X-Fouine-Jeton": serveur.jeton}
                if corps is not None:
                    entetes["Content-Type"] = "application/json"
                try:
                    connexion.request(
                        methode, chemin, body=None if corps is None else json.dumps(corps).encode(), headers=entetes
                    )
                    reponse = connexion.getresponse()
                    contenu = reponse.read()
                finally:
                    connexion.close()
                if reponse.status != 200:
                    raise RuntimeError(f"{methode} {chemin} : réponse {reponse.status}")
                if reponse.getheader("Content-Type", "").startswith("application/json"):
                    return json.loads(contenu)
                return contenu

            etape(f"serveur local démarré sur 127.0.0.1:{port}")
            for chemin, attendu in (("/", b"<title>Fouine</title>"), ("/app.js", b"use strict"), ("/style.css", b"--fond")):
                if attendu not in demander("GET", chemin):
                    raise RuntimeError(f"page {chemin} inattendue")
            etape("page, script et feuille de style servis")
            demander("POST", "/api/indexer", {})
            application.attendre(60)
            etat = demander("GET", "/api/etat")
            if etat["tache"]["erreur"] or etat["tache"]["en_cours"]:
                raise RuntimeError(f"indexation : {etat['tache']['erreur'] or 'pas finie'}")
            if (etat["index"]["fichiers"], etat["index"]["images"]) != (4, 2):
                raise RuntimeError(f"index inattendu : {etat['index']}")
            etape("indexation : 2 documents et 2 images lus, l'icône écartée")
            trouves = demander("POST", "/api/recherche", {"question": "fuite sous l'évier"})["resultats"]
            if [r["nom"] for r in trouves][:1] != ["Facture du plombier.txt"]:
                raise RuntimeError("recherche de documents : mauvais résultat")
            etape("recherche de documents (les accents sont bien lus)")
            images = demander("POST", "/api/recherche_images", {"question": "rouge"})["images"]
            if [r["nom"] for r in images] != ["tomate.jpg", "mer.png"]:
                raise RuntimeError("recherche d'images : mauvais résultat")
            vignette = Image.open(io.BytesIO(demander("GET", f"/api/vignette?id={images[0]['id']}")))
            if vignette.format != "JPEG":
                raise RuntimeError("vignette inattendue")
            etape("recherche d'images et vignette")
        finally:
            serveur.shutdown()
            serveur.server_close()
            fil.join(10)
            index.fermer()
    print("Auto-test réussi.", flush=True)
    return 0
