"""Faux modèles, pour les tests et pour l'auto-test du programme (`--autotest`).

Ils ont la même forme que les vrais, mais ne téléchargent rien et répondent tout
de suite. Ils ne servent jamais dans une utilisation normale de Fouine.
"""

from __future__ import annotations

import hashlib
import re

import numpy as np

from .embedding import normaliser

_COULEURS = {
    "rouge": (1.0, 0.0, 0.0),
    "vert": (0.0, 1.0, 0.0),
    "verte": (0.0, 1.0, 0.0),
    "bleu": (0.0, 0.0, 1.0),
    "bleue": (0.0, 0.0, 1.0),
}


class FauxEmbedding:
    """Remplace le modèle des textes : deux textes qui partagent des mots ont des vecteurs proches."""

    nom = "faux-modele"
    dimension = 384

    def __init__(self):
        self.appels = 0
        self.textes_vus: list[str] = []

    def pret(self) -> bool:
        return True

    def vecteurs(self, textes):
        self.appels += 1
        self.textes_vus.extend(textes)
        matrice = np.zeros((len(textes), self.dimension), dtype=np.float32)
        for ligne, texte in enumerate(textes):
            for mot in re.findall(r"\w+", texte.lower()):
                case = int.from_bytes(hashlib.md5(mot.encode()).digest()[:4], "big") % self.dimension
                matrice[ligne, case] += 1.0
        return normaliser(matrice)

    def vecteur_question(self, question):
        return self.vecteurs([question])[0]


class FauxEmbeddingImages:
    """Remplace le modèle des images : il ne « voit » que la couleur moyenne.

    La question « rouge » ressemble donc à une image rouge, « bleu » à une image bleue.
    """

    nom = "faux-modele-images"
    dimension = 256

    def __init__(self):
        self.images_vues = 0
        self.chargements = 0
        self._pret = False

    def pret(self) -> bool:
        return self._pret

    def charger(self) -> None:
        if not self._pret:
            self.chargements += 1
            self._pret = True

    def _vecteur(self, rouge, vert, bleu) -> np.ndarray:
        vecteur = np.zeros((1, self.dimension), dtype=np.float32)
        vecteur[0, :3] = (rouge, vert, bleu)
        vecteur[0, 3] = 0.05  # jamais un vecteur nul
        return normaliser(vecteur)[0]

    def vecteur_image(self, image) -> np.ndarray:
        self.charger()
        self.images_vues += 1
        moyenne = np.asarray(image.convert("RGB"), dtype=np.float32).reshape(-1, 3).mean(axis=0) / 255.0
        return self._vecteur(*moyenne)

    def vecteur_question(self, question: str) -> np.ndarray:
        self.charger()
        somme = np.zeros(3, dtype=np.float32)
        for mot in re.findall(r"\w+", question.lower()):
            somme += np.array(_COULEURS.get(mot, (0.0, 0.0, 0.0)), dtype=np.float32)
        return self._vecteur(*somme)
