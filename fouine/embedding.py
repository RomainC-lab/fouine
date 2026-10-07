"""Transforme un texte en une liste de nombres (« vecteur ») qui représente son sens.

Le calcul se fait sur le PC avec un petit modèle multilingue. Le modèle est
téléchargé une seule fois, au premier besoin : c'est le seul moment où Fouine
se connecte à Internet. Ensuite il est relu depuis le disque, sans connexion.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np

MODELE = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DIMENSION = 384
TAILLE_MODELE = "environ 220 Mo"


def normaliser(vecteurs: np.ndarray) -> np.ndarray:
    vecteurs = np.asarray(vecteurs, dtype=np.float32)
    normes = np.linalg.norm(vecteurs, axis=1, keepdims=True)
    normes[normes == 0] = 1.0
    return vecteurs / normes


class Embedding:
    """Charge le modèle quand on en a besoin, puis calcule les vecteurs."""

    nom = MODELE
    dimension = DIMENSION

    def __init__(self, dossier_modele: Path):
        self.dossier = Path(dossier_modele)
        self._modele = None
        self._verrou = threading.Lock()
        self.telechargement = False  # vrai pendant le tout premier téléchargement

    def _charger(self):
        with self._verrou:
            if self._modele is not None:
                return self._modele
            # Aucune statistique d'usage envoyée par les bibliothèques utilisées.
            os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
            os.environ.setdefault("DO_NOT_TRACK", "1")
            from fastembed import TextEmbedding

            try:  # pas de messages techniques en anglais dans la console
                from loguru import logger

                logger.disable("fastembed")
            except ImportError:
                pass
            self.dossier.mkdir(parents=True, exist_ok=True)
            fils = max(1, min(4, (os.cpu_count() or 2) - 1))
            try:
                # D'abord sans réseau : le modèle déjà téléchargé suffit.
                self._modele = TextEmbedding(
                    MODELE, cache_dir=str(self.dossier), threads=fils, local_files_only=True
                )
            except Exception:
                self.telechargement = True
                try:
                    self._modele = TextEmbedding(MODELE, cache_dir=str(self.dossier), threads=fils)
                finally:
                    self.telechargement = False
            return self._modele

    def pret(self) -> bool:
        return self._modele is not None

    def vecteurs(self, textes: list[str]) -> np.ndarray:
        """Un vecteur par texte, de longueur 1 (prêt pour comparer par produit)."""
        if not textes:
            return np.zeros((0, DIMENSION), dtype=np.float32)
        modele = self._charger()
        return normaliser(np.array(list(modele.embed(textes, batch_size=16))))

    def vecteur_question(self, question: str) -> np.ndarray:
        return self.vecteurs([question])[0]
