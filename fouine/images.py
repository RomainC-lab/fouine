"""Les images : les ouvrir sans risque, en faire une vignette, et calculer leur « empreinte de sens ».

Le texte des documents garde son petit modèle. Les images en demandent un second
(EmbeddingGemma 2, de Google, licence Apache 2.0), qui range dans le même espace
une image et la phrase qui la décrit. Il n'est téléchargé et chargé que si
l'option « Lire aussi les images » est cochée. Le calcul se fait sur le PC, avec
ONNX Runtime.
"""

from __future__ import annotations

import math
import os
import threading
import warnings
from pathlib import Path

import numpy as np

from .embedding import normaliser
from .extraction import Illisible
from .reglages import EXTENSIONS_IMAGES

# Au-delà de ce nombre de points, une image n'est pas décodée (elle remplirait la mémoire).
PIXELS_MAX = 120_000_000
COTE_VIGNETTE = 360

DEPOT = "onnx-community/embeddinggemma-2-ONNX"
# Version précise du dépôt : les poids ne changent pas sans une nouvelle version de Fouine.
REVISION = "daa72c51243991dfcaf9f9137d2c573d8f7790c0"
VARIANTE = "q4"
JETONS_PAR_IMAGE = 70
DIMENSION_IMAGES = 256  # les 256 premiers nombres suffisent (vérifié sur le jeu d'essai)
TAILLE_MODELE_IMAGES = "environ 315 Mo"
_FICHIERS = [
    "tokenizer.json",
    f"onnx/model_{VARIANTE}.onnx",
    f"onnx/model_{VARIANTE}.onnx_data",
    f"onnx/vision_encoder_{VARIANTE}.onnx",
    f"onnx/vision_encoder_{VARIANTE}.onnx_data",
]
_PREFIXE_QUESTION = "task: search result | query: "
_COTE_PATCH = 16
_REGROUPEMENT = 3


def est_image(chemin: str) -> bool:
    return os.path.splitext(chemin)[1].lower() in EXTENSIONS_IMAGES


def _pillow():
    from PIL import Image

    # Pillow refuse de lui-même les images démesurées (au-delà du double de cette limite).
    Image.MAX_IMAGE_PIXELS = PIXELS_MAX
    return Image


def dimensions(chemin: str) -> tuple[int, int] | None:
    """Largeur et hauteur en points, en ne lisant que l'en-tête. None si ce n'est pas lisible."""
    try:
        Image = _pillow()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with Image.open(chemin) as image:
                return int(image.width), int(image.height)
    except Exception:  # fichier abîmé, faux fichier image, accès refusé…
        return None


def ouvrir(chemin: str):
    """Rend (image, (largeur, hauteur) d'origine) : l'image est décodée, en couleurs, dans
    le bon sens, et peut avoir été réduite au passage. Lève `Illisible` si ce n'est pas possible."""
    try:
        Image = _pillow()
        from PIL import ImageOps

        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(chemin) as image:
                if image.width * image.height > PIXELS_MAX:
                    raise Illisible("Image trop grande pour être lue")
                if image.width < 1 or image.height < 1:
                    raise Illisible("Image vide")
                origine = (int(image.width), int(image.height))
                # Un grand JPEG est décodé directement en plus petit : plus rapide, moins de mémoire.
                image.draft("RGB", (1024, 1024))
                image.seek(0)  # GIF, TIFF à plusieurs pages : la première image
                image.load()
                droite = ImageOps.exif_transpose(image)
                if droite.mode in ("RGBA", "LA", "P"):
                    # Fond blanc sous les zones transparentes (noir par défaut sinon).
                    droite = droite.convert("RGBA")
                    fond = Image.new("RGB", droite.size, (255, 255, 255))
                    fond.paste(droite, mask=droite.getchannel("A"))
                    return fond, origine
                return droite.convert("RGB"), origine
    except Illisible:
        raise
    except PermissionError:
        raise Illisible("Accès refusé") from None
    except FileNotFoundError:
        raise Illisible("Fichier introuvable") from None
    except MemoryError:
        raise Illisible("Image trop grande pour être lue") from None
    except Exception as erreur:
        if type(erreur).__name__ in ("DecompressionBombError", "DecompressionBombWarning"):
            raise Illisible("Image trop grande pour être lue") from None
        raise Illisible("Image abîmée ou dans un format inattendu") from None


def vignette(image, destination: Path) -> None:
    """Enregistre une petite copie JPEG de l'image (pour la grille de résultats)."""
    Image = _pillow()
    petite = image.copy()
    petite.thumbnail((COTE_VIGNETTE, COTE_VIGNETTE), Image.LANCZOS)
    destination.parent.mkdir(parents=True, exist_ok=True)
    provisoire = destination.with_suffix(".tmp")
    petite.save(provisoire, "JPEG", quality=82, optimize=True)
    os.replace(provisoire, destination)


def preparer(image, jetons: int = JETONS_PAR_IMAGE):
    """Découpe l'image en petits carrés, comme le modèle les attend.

    Même préparation que celle de transformers.js pour ce modèle : l'image est
    ramenée à une taille qui donne au plus `jetons` jetons, en gardant ses proportions.
    """
    Image = _pillow()
    cote = _REGROUPEMENT * _COTE_PATCH
    maximum = jetons * _REGROUPEMENT * _REGROUPEMENT
    facteur = math.sqrt(maximum * _COTE_PATCH * _COTE_PATCH / (image.height * image.width))
    hauteur = max(cote, math.floor(facteur * image.height / cote) * cote)
    largeur = max(cote, math.floor(facteur * image.width / cote) * cote)
    # Image très allongée : le côté court est remonté à 48 points, le long est raccourci d'autant.
    while (hauteur // _COTE_PATCH) * (largeur // _COTE_PATCH) > maximum:
        if largeur >= hauteur:
            largeur -= cote
        else:
            hauteur -= cote
    image = image.resize((largeur, hauteur), Image.BICUBIC)
    points = np.asarray(image, dtype=np.float32) / 255.0
    lignes, colonnes = hauteur // _COTE_PATCH, largeur // _COTE_PATCH
    patchs = (
        points.reshape(lignes, _COTE_PATCH, colonnes, _COTE_PATCH, 3)
        .transpose(0, 2, 1, 3, 4)
        .reshape(lignes * colonnes, _COTE_PATCH * _COTE_PATCH * 3)
    )
    x, y = np.meshgrid(np.arange(colonnes), np.arange(lignes))
    positions = np.stack([x.ravel(), y.ravel()], axis=-1).astype(np.int64)
    return patchs, positions, (lignes * colonnes) // (_REGROUPEMENT * _REGROUPEMENT)


def raccourcir(vecteurs: np.ndarray) -> np.ndarray:
    """Garde le début de chaque vecteur et le remet à la longueur 1."""
    return normaliser(np.asarray(vecteurs, dtype=np.float32)[:, :DIMENSION_IMAGES])


class EmbeddingImages:
    """Le second modèle : chargé seulement quand on lit ou qu'on cherche des images."""

    nom = f"{DEPOT}@{REVISION[:12]} {VARIANTE} {JETONS_PAR_IMAGE}j {DIMENSION_IMAGES}d"
    dimension = DIMENSION_IMAGES

    def __init__(self, dossier_modele: Path):
        self.dossier = Path(dossier_modele)
        self._sessions = None
        self._verrou = threading.Lock()
        self._calcul = threading.Lock()
        self.telechargement = False  # vrai pendant le tout premier téléchargement

    def pret(self) -> bool:
        return self._sessions is not None

    def _fichiers(self) -> Path:
        """Le dossier des poids ; les télécharge la première fois (seul accès au réseau)."""
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        os.environ.setdefault("DO_NOT_TRACK", "1")
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        from huggingface_hub import snapshot_download
        from huggingface_hub.utils import disable_progress_bars, logging as journal

        disable_progress_bars()  # pas de messages techniques en anglais dans la console
        journal.set_verbosity_error()

        # De vrais fichiers dans un dossier simple (pas le cache à liens de Hugging Face) :
        # ONNX Runtime exige que les poids soient à côté du modèle, et Windows gère mal les liens.
        if all((self.dossier / nom).is_file() for nom in _FICHIERS):
            return self.dossier
        self.dossier.mkdir(parents=True, exist_ok=True)
        self.telechargement = True
        try:
            # Un fichier n'apparaît sous son nom qu'une fois entièrement téléchargé.
            snapshot_download(
                repo_id=DEPOT, revision=REVISION, allow_patterns=_FICHIERS, local_dir=str(self.dossier)
            )
        finally:
            self.telechargement = False
        return self.dossier

    def charger(self) -> None:
        with self._verrou:
            if self._sessions is not None:
                return
            racine = self._fichiers()
            import onnxruntime
            from tokenizers import Tokenizer

            options = onnxruntime.SessionOptions()
            options.intra_op_num_threads = max(1, min(4, (os.cpu_count() or 2) - 1))
            options.log_severity_level = 3  # pas de messages techniques en anglais dans la console
            decoupeur = Tokenizer.from_file(str(racine / "tokenizer.json"))
            decoupeur.no_padding()
            decoupeur.no_truncation()

            def session(nom):
                return onnxruntime.InferenceSession(
                    str(racine / "onnx" / nom), options, providers=["CPUExecutionProvider"]
                )

            self._sessions = (
                decoupeur,
                session(f"model_{VARIANTE}.onnx"),
                session(f"vision_encoder_{VARIANTE}.onnx"),
            )

    def _encoder(self, texte: str, traits_image=None) -> np.ndarray:
        decoupeur, modele, _ = self._sessions
        identifiants = np.array([decoupeur.encode(texte).ids], dtype=np.int64)
        vide = np.zeros((0, 512), dtype=np.float32)
        sortie = modele.run(
            ["sentence_embedding"],
            {
                "input_ids": identifiants,
                "attention_mask": np.ones_like(identifiants),
                "image_features": vide if traits_image is None else traits_image,
                "video_features": vide,
                "audio_features": vide,
            },
        )[0]
        return raccourcir(sortie)[0]

    def vecteur_image(self, image) -> np.ndarray:
        """Le vecteur d'une image déjà ouverte (voir `ouvrir`)."""
        self.charger()
        patchs, positions, jetons = preparer(image)
        with self._calcul:
            traits = self._sessions[2].run(
                None, {"pixel_values": patchs[None], "pixel_position_ids": positions[None]}
            )[0]
            return self._encoder("<|image>" + "<|image|>" * jetons + "<image|>", traits)

    def vecteur_question(self, question: str) -> np.ndarray:
        self.charger()
        with self._calcul:
            return self._encoder(_PREFIXE_QUESTION + question)
