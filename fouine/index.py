"""L'index : un fichier SQLite qui garde, pour chaque fichier lu, ses morceaux de texte
et leurs vecteurs ; pour chaque image, son vecteur. Sert à indexer (sans relire ce qui
n'a pas changé) et à chercher.
"""

from __future__ import annotations

import os
import re
import sqlite3
import statistics
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from . import images as mod_images
from .extraction import Illisible, decouper, extraire
from .filtres import _est_dans, parcourir, racines_utiles

NOM_BASE = "index.sqlite"
DOSSIER_VIGNETTES = "vignettes"
# Les scores des images sont serrés (une image sans rapport fait déjà 0,55 à 0,60) :
# pas de seuil, on montre les plus proches.
IMAGES_MONTREES = 12
_K_FUSION = 60  # constante habituelle du mélange par rangs (« reciprocal rank fusion »)
_CANDIDATS = 60
# En dessous de cette ressemblance, un passage n'a pas de rapport avec la question.
_SEUIL_SENS = 0.30

_MOTS_VIDES = set(
    "a à au aux avec ce ces cet cette dans de des du elle en et est il ils je la le les leur lui ma mais me mes "
    "mon ne nos notre nous on ou où par pas pour qu que qui sa se ses son sur ta te tes ton tu un une vos votre "
    "vous y d l j n s t c m the of and to in is it for on with an or at by be this that are was".split()
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (cle TEXT PRIMARY KEY, valeur TEXT);
CREATE TABLE IF NOT EXISTS fichiers (
    id INTEGER PRIMARY KEY,
    chemin TEXT NOT NULL UNIQUE,
    taille INTEGER NOT NULL,
    modifie INTEGER NOT NULL,
    erreur TEXT,
    indexe_le REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS morceaux (
    id INTEGER PRIMARY KEY,
    fichier_id INTEGER NOT NULL REFERENCES fichiers(id) ON DELETE CASCADE,
    rang INTEGER NOT NULL,
    texte TEXT NOT NULL,
    vecteur BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS morceaux_par_fichier ON morceaux(fichier_id);
CREATE TABLE IF NOT EXISTS images (
    fichier_id INTEGER PRIMARY KEY REFERENCES fichiers(id) ON DELETE CASCADE,
    largeur INTEGER NOT NULL,
    hauteur INTEGER NOT NULL,
    vecteur BLOB NOT NULL
);
"""


class Index:
    def __init__(self, dossier: Path, embedding, embedding_images=None):
        self.dossier = Path(dossier)
        self.dossier.mkdir(parents=True, exist_ok=True)
        self.base = self.dossier / NOM_BASE
        self.vignettes = self.dossier / DOSSIER_VIGNETTES
        self.embedding = embedding
        self.embedding_images = embedding_images  # None : les images ne sont pas lues
        self._cache_images = None
        self._local = threading.local()
        self._version = 0
        self._cache = None  # (version, identifiants, matrice)
        self._verrou_cache = threading.Lock()
        cx = self._cx()
        cx.executescript(_SCHEMA)
        # Index créé par une version d'avant les images : il est gardé tel quel, on ajoute
        # seulement la colonne qui distingue un document d'une image.
        if "genre" not in [ligne[1] for ligne in cx.execute("PRAGMA table_info(fichiers)")]:
            cx.execute("ALTER TABLE fichiers ADD COLUMN genre TEXT NOT NULL DEFAULT 'texte'")
        self.mots = self._creer_recherche_par_mots(cx)
        self._verifier_modele(cx)
        cx.commit()

    # ---------------------------------------------------------------- base

    def _cx(self) -> sqlite3.Connection:
        cx = getattr(self._local, "cx", None)
        if cx is None:
            cx = sqlite3.connect(self.base, timeout=30)
            cx.execute("PRAGMA journal_mode=WAL")
            cx.execute("PRAGMA foreign_keys=ON")
            self._local.cx = cx
        return cx

    def fermer(self) -> None:
        cx = getattr(self._local, "cx", None)
        if cx is not None:
            cx.close()
            self._local.cx = None

    @staticmethod
    def _creer_recherche_par_mots(cx) -> bool:
        """Recherche par mots (FTS5), si la version de SQLite du PC la propose."""
        try:
            cx.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS mots USING fts5("
                "texte, nom, tokenize='unicode61 remove_diacritics 2')"
            )
            return True
        except sqlite3.OperationalError:
            return False

    def _verifier_modele(self, cx) -> None:
        """Si le modèle a changé, les anciens vecteurs ne valent plus rien : on repart de zéro."""
        ligne = cx.execute("SELECT valeur FROM meta WHERE cle='modele'").fetchone()
        if ligne and ligne[0] != self.embedding.nom:
            cx.execute("DELETE FROM fichiers WHERE genre='texte'")
            cx.execute("DELETE FROM morceaux")
            if self.mots:
                cx.execute("DELETE FROM mots")
        cx.execute("INSERT OR REPLACE INTO meta VALUES ('modele', ?)", (self.embedding.nom,))
        if self.embedding_images is None:
            return
        ligne = cx.execute("SELECT valeur FROM meta WHERE cle='modele_images'").fetchone()
        if ligne and ligne[0] != self.embedding_images.nom:
            for (fichier_id,) in cx.execute("SELECT id FROM fichiers WHERE genre='image'").fetchall():
                self._retirer(cx, fichier_id)
            cx.execute("DELETE FROM meta WHERE cle='secondes_par_image'")
        cx.execute("INSERT OR REPLACE INTO meta VALUES ('modele_images', ?)", (self.embedding_images.nom,))

    def _retirer(self, cx, fichier_id: int) -> None:
        if self.mots:
            cx.execute("DELETE FROM mots WHERE rowid IN (SELECT id FROM morceaux WHERE fichier_id=?)", (fichier_id,))
        cx.execute("DELETE FROM morceaux WHERE fichier_id=?", (fichier_id,))
        cx.execute("DELETE FROM images WHERE fichier_id=?", (fichier_id,))
        cx.execute("DELETE FROM fichiers WHERE id=?", (fichier_id,))
        try:
            self._vignette(fichier_id).unlink()
        except OSError:
            pass

    def _vignette(self, fichier_id: int) -> Path:
        return self.vignettes / f"{int(fichier_id)}.jpg"

    def memoire(self):
        """Ce que l'index sait déjà, pour que le parcours des dossiers aille vite.

        Rend deux fonctions : `dimensions(chemin, taille, modifie)` donne la taille en points
        d'une image déjà lue et inchangée ; `deja_lu(element)` dit si un fichier est déjà
        dans l'index, inchangé.
        """
        connus = {
            chemin: (taille, modifie, largeur, hauteur)
            for chemin, taille, modifie, largeur, hauteur in self._cx().execute(
                "SELECT f.chemin, f.taille, f.modifie, i.largeur, i.hauteur "
                "FROM fichiers f LEFT JOIN images i ON i.fichier_id = f.id"
            )
        }

        def dimensions(chemin, taille, modifie):
            connu = connus.get(chemin)
            if connu and connu[0] == taille and connu[1] == modifie and connu[2]:
                return connu[2], connu[3]
            return None

        def deja_lu(element):
            connu = connus.get(element.chemin)
            return bool(connu and connu[0] == element.taille and connu[1] == element.modifie)

        return dimensions, deja_lu

    # ----------------------------------------------------------- indexation

    def indexer(self, reglages: dict, progression=None, arret=None) -> dict:
        """Met l'index à jour. Ne relit que les fichiers nouveaux ou modifiés.

        Chaque fichier est enregistré dès qu'il est fini : si on arrête en route,
        ce qui est fait reste fait, et le prochain lancement reprend la suite.
        """
        arret = arret or (lambda: False)
        signaler = progression or (lambda **infos: None)
        cx = self._cx()
        bilan = {
            "nouveaux": 0, "modifies": 0, "inchanges": 0, "retires": 0, "illisibles": 0, "images": 0,
            "arrete": False,
        }

        signaler(etape="parcours", fait=0, total=0, fichier="")
        connus = {
            chemin: (fid, taille, modifie)
            for fid, chemin, taille, modifie in cx.execute("SELECT id, chemin, taille, modifie FROM fichiers")
        }
        a_faire = []
        vus = set()
        for element in parcourir(reglages, arret, self.memoire()[0], self.dossier):
            if element.raison is not None or (element.image and self.embedding_images is None):
                continue
            vus.add(element.chemin)
            connu = connus.get(element.chemin)
            if connu and connu[1] == element.taille and connu[2] == element.modifie:
                bilan["inchanges"] += 1
            else:
                a_faire.append(element)
        if arret():
            bilan["arrete"] = True
            return bilan

        # Fichiers supprimés, ou désormais écartés par les filtres : ils sortent de l'index.
        # Ceux d'un dossier momentanément absent (clé USB débranchée…) sont gardés.
        _, absents = racines_utiles(reglages["dossiers"])
        for chemin, (fid, _, _) in connus.items():
            if chemin not in vus and not any(_est_dans(chemin, absent) for absent in absents):
                self._retirer(cx, fid)
                bilan["retires"] += 1
        cx.commit()
        self._version += 1

        # Les documents d'abord (rapides), les images ensuite (quelques secondes chacune).
        a_faire.sort(key=lambda element: element.image)
        total = len(a_faire)
        durees: list[float] = []  # secondes passées sur chaque image, pour estimer la suite
        for numero, element in enumerate(a_faire):
            if arret():
                bilan["arrete"] = True
                break
            reste = None
            if len(durees) >= 3:
                reste = round(statistics.median(durees) * (total - numero))
            if element.image and not self.embedding_images.pret():
                signaler(etape="modele_images", fait=numero, total=total, fichier="", reste_s=None)
                self.embedding_images.charger()
            signaler(etape="lecture", fait=numero, total=total, fichier=element.chemin, reste_s=reste)
            deja = element.chemin in connus
            if element.image:
                debut = time.monotonic()
                self._indexer_image(cx, element)
                durees.append(time.monotonic() - debut)
            elif not self._indexer_fichier(cx, element, arret):
                bilan["arrete"] = True
                break
            erreur = cx.execute("SELECT erreur FROM fichiers WHERE chemin=?", (element.chemin,)).fetchone()
            if erreur and erreur[0]:
                bilan["illisibles"] += 1
            else:
                bilan["modifies" if deja else "nouveaux"] += 1
                bilan["images"] += element.image
        if len(durees) >= 3:
            # Vitesse mesurée sur ce PC : sert à annoncer une durée la prochaine fois.
            cx.execute(
                "INSERT OR REPLACE INTO meta VALUES ('secondes_par_image', ?)", (str(statistics.median(durees)),)
            )
        cx.execute("INSERT OR REPLACE INTO meta VALUES ('derniere_indexation', ?)", (str(time.time()),))
        cx.commit()
        self._menage_vignettes(cx)
        signaler(etape="fini", fait=total, total=total, fichier="", reste_s=None)
        return bilan

    def _indexer_image(self, cx, element) -> None:
        """Ouvre une image, calcule son vecteur, garde une vignette. Jamais d'erreur vers l'appelant."""
        erreur = None
        image = vecteur = None
        origine = (0, 0)
        try:
            image, origine = mod_images.ouvrir(element.chemin)
            vecteur = np.asarray(self.embedding_images.vecteur_image(image), dtype=np.float32)
        except Illisible as probleme:
            erreur = str(probleme)
        except Exception:  # image que le modèle n'accepte pas : notée, et on continue
            erreur = "Image que Fouine n'a pas su lire"
        ancien = cx.execute("SELECT id FROM fichiers WHERE chemin=?", (element.chemin,)).fetchone()
        if ancien:
            self._retirer(cx, ancien[0])
        fichier_id = cx.execute(
            "INSERT INTO fichiers (chemin, taille, modifie, erreur, indexe_le, genre) VALUES (?, ?, ?, ?, ?, 'image')",
            (element.chemin, element.taille, element.modifie, erreur, time.time()),
        ).lastrowid
        if erreur is None:
            cx.execute(
                "INSERT INTO images (fichier_id, largeur, hauteur, vecteur) VALUES (?, ?, ?, ?)",
                (fichier_id, origine[0], origine[1], vecteur.tobytes()),
            )
            try:
                mod_images.vignette(image, self._vignette(fichier_id))
            except Exception:  # la vignette sera refaite à la demande
                pass
        cx.commit()
        self._version += 1

    def _menage_vignettes(self, cx) -> None:
        """Supprime les vignettes d'images qui ne sont plus dans l'index."""
        gardees = {f"{fichier_id}.jpg" for (fichier_id,) in cx.execute("SELECT fichier_id FROM images")}
        try:
            for entree in os.scandir(self.vignettes):
                if entree.name not in gardees:
                    os.unlink(entree.path)
        except OSError:
            pass

    def _indexer_fichier(self, cx, element, arret) -> bool:
        """Lit un fichier et l'enregistre. Rend False si on a demandé l'arrêt en cours de route."""
        erreur = None
        morceaux: list[str] = []
        try:
            morceaux = decouper(extraire(element.chemin))
        except Illisible as probleme:
            erreur = str(probleme)
        nom = os.path.basename(element.chemin)
        titre = os.path.splitext(nom)[0].replace("_", " ").replace("-", " ")
        if not erreur and not morceaux:
            # Pas de texte (PDF scanné par exemple) : au moins, le nom reste trouvable.
            morceaux = [titre]
        vecteurs = []
        a_calculer = [titre + "\n" + morceaux[0]] + morceaux[1:] if morceaux else []
        for debut in range(0, len(a_calculer), 32):
            if arret():
                return False
            vecteurs.append(self.embedding.vecteurs(a_calculer[debut:debut + 32]))

        ancien = cx.execute("SELECT id FROM fichiers WHERE chemin=?", (element.chemin,)).fetchone()
        if ancien:
            self._retirer(cx, ancien[0])
        curseur = cx.execute(
            "INSERT INTO fichiers (chemin, taille, modifie, erreur, indexe_le) VALUES (?, ?, ?, ?, ?)",
            (element.chemin, element.taille, element.modifie, erreur, time.time()),
        )
        fichier_id = curseur.lastrowid
        if morceaux:
            matrice = np.vstack(vecteurs).astype(np.float32)
            for rang, (texte, vecteur) in enumerate(zip(morceaux, matrice)):
                identifiant = cx.execute(
                    "INSERT INTO morceaux (fichier_id, rang, texte, vecteur) VALUES (?, ?, ?, ?)",
                    (fichier_id, rang, texte, vecteur.tobytes()),
                ).lastrowid
                if self.mots:
                    cx.execute("INSERT INTO mots (rowid, texte, nom) VALUES (?, ?, ?)", (identifiant, texte, nom))
        cx.commit()
        self._version += 1
        return True

    # ------------------------------------------------------------ recherche

    def _matrice(self):
        with self._verrou_cache:
            if self._cache and self._cache[0] == self._version:
                return self._cache[1], self._cache[2]
            version = self._version
            lignes = self._cx().execute("SELECT id, vecteur FROM morceaux ORDER BY id").fetchall()
            identifiants = np.array([ligne[0] for ligne in lignes], dtype=np.int64)
            dimension = self.embedding.dimension
            if lignes:
                matrice = np.frombuffer(b"".join(ligne[1] for ligne in lignes), dtype=np.float32)
                matrice = matrice.reshape(len(lignes), dimension)
            else:
                matrice = np.zeros((0, dimension), dtype=np.float32)
            self._cache = (version, identifiants, matrice)
            return identifiants, matrice

    def _par_sens(self, question: str) -> list[int]:
        identifiants, matrice = self._matrice()
        if not len(identifiants):
            return []
        scores = matrice @ self.embedding.vecteur_question(question)
        ordre = np.argsort(-scores)[:_CANDIDATS]
        return [int(identifiants[i]) for i in ordre if scores[i] >= _SEUIL_SENS]

    def _par_mots(self, mots: list[str]) -> list[int]:
        if not self.mots or not mots:
            return []
        requete = " OR ".join('"' + mot.replace('"', "") + '"*' for mot in mots)
        try:
            lignes = self._cx().execute(
                "SELECT rowid FROM mots WHERE mots MATCH ? ORDER BY bm25(mots, 1.0, 3.0) LIMIT ?",
                (requete, _CANDIDATS),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [ligne[0] for ligne in lignes]

    def rechercher(self, question: str, limite: int = 20) -> list[dict]:
        """Mélange la recherche par le sens et la recherche par mots ; un résultat par fichier."""
        question = " ".join(question.split())[:500]
        if not question:
            return []
        tous = [mot for mot in re.findall(r"\w+", question.lower()) if len(mot) > 1]
        mots = [mot for mot in tous if mot not in _MOTS_VIDES] or tous

        scores: dict[int, float] = {}
        origine: dict[int, set] = {}
        for nom, classement in (("sens", self._par_sens(question)), ("mots", self._par_mots(mots))):
            for rang, identifiant in enumerate(classement):
                scores[identifiant] = scores.get(identifiant, 0.0) + 1.0 / (_K_FUSION + rang + 1)
                origine.setdefault(identifiant, set()).add(nom)
        if not scores:
            return []

        cx = self._cx()
        meilleurs: dict[int, dict] = {}
        for identifiant in sorted(scores, key=lambda i: -scores[i]):
            ligne = cx.execute(
                "SELECT f.id, f.chemin, f.modifie, f.taille, m.texte FROM morceaux m "
                "JOIN fichiers f ON f.id = m.fichier_id WHERE m.id=?",
                (identifiant,),
            ).fetchone()
            if not ligne or ligne[0] in meilleurs:
                continue
            fichier_id, chemin, modifie, taille, texte = ligne
            meilleurs[fichier_id] = {
                "id": fichier_id,
                "chemin": chemin,
                "nom": os.path.basename(chemin),
                "dossier": os.path.dirname(chemin),
                "modifie": datetime.fromtimestamp(modifie / 1e9).strftime("%d/%m/%Y"),
                "taille": taille,
                "extrait": _extrait(texte, mots),
                "trouve_par": sorted(origine[identifiant]),
            }
            if len(meilleurs) >= limite:
                break
        return list(meilleurs.values())

    def _matrice_images(self):
        with self._verrou_cache:
            if self._cache_images and self._cache_images[0] == self._version:
                return self._cache_images[1], self._cache_images[2]
            version = self._version
            lignes = self._cx().execute("SELECT fichier_id, vecteur FROM images ORDER BY fichier_id").fetchall()
            identifiants = np.array([ligne[0] for ligne in lignes], dtype=np.int64)
            dimension = self.embedding_images.dimension
            matrice = np.frombuffer(b"".join(ligne[1] for ligne in lignes), dtype=np.float32)
            matrice = matrice.reshape(len(lignes), dimension)
            self._cache_images = (version, identifiants, matrice)
            return identifiants, matrice

    def rechercher_images(self, question: str, limite: int = IMAGES_MONTREES) -> list[dict]:
        """Les images les plus proches de la question, de la plus proche à la moins proche.

        Liste à part de celle des documents : les deux modèles ne notent pas pareil,
        leurs scores ne se comparent pas.
        """
        question = " ".join(question.split())[:500]
        if not question or self.embedding_images is None:
            return []
        identifiants, matrice = self._matrice_images()
        if not len(identifiants):
            return []
        scores = matrice @ self.embedding_images.vecteur_question(question)
        cx = self._cx()
        resultats = []
        for i in np.argsort(-scores)[:limite]:
            ligne = cx.execute(
                "SELECT f.chemin, f.modifie, f.taille, i.largeur, i.hauteur FROM fichiers f "
                "JOIN images i ON i.fichier_id = f.id WHERE f.id=?",
                (int(identifiants[i]),),
            ).fetchone()
            if not ligne:
                continue
            chemin, modifie, taille, largeur, hauteur = ligne
            resultats.append({
                "id": int(identifiants[i]),
                "chemin": chemin,
                "nom": os.path.basename(chemin),
                "dossier": os.path.dirname(chemin),
                "modifie": datetime.fromtimestamp(modifie / 1e9).strftime("%d/%m/%Y"),
                "taille": taille,
                "largeur": largeur,
                "hauteur": hauteur,
                "score": round(float(scores[i]), 3),
            })
        return resultats

    def vignette(self, fichier_id) -> bytes | None:
        """La vignette (JPEG) d'une image de l'index ; None pour tout autre fichier."""
        if isinstance(fichier_id, bool) or not isinstance(fichier_id, int):
            return None
        ligne = self._cx().execute(
            "SELECT f.chemin FROM fichiers f JOIN images i ON i.fichier_id = f.id WHERE f.id=?", (fichier_id,)
        ).fetchone()
        if not ligne:
            return None
        fichier = self._vignette(fichier_id)
        try:
            return fichier.read_bytes()
        except OSError:
            pass
        try:  # vignette effacée entre-temps : refaite à partir de l'image
            image, _ = mod_images.ouvrir(ligne[0])
            mod_images.vignette(image, fichier)
            return fichier.read_bytes()
        except (Illisible, OSError):
            return None

    # ---------------------------------------------------------------- infos

    def chemin(self, fichier_id) -> str | None:
        """Le chemin d'un fichier de l'index, ou None s'il n'y est pas."""
        if isinstance(fichier_id, bool) or not isinstance(fichier_id, int):
            return None
        ligne = self._cx().execute("SELECT chemin FROM fichiers WHERE id=?", (fichier_id,)).fetchone()
        return ligne[0] if ligne else None

    def statistiques(self) -> dict:
        cx = self._cx()
        fichiers, illisibles = cx.execute(
            "SELECT COUNT(*), COALESCE(SUM(erreur IS NOT NULL), 0) FROM fichiers"
        ).fetchone()
        morceaux = cx.execute("SELECT COUNT(*) FROM morceaux").fetchone()[0]
        nombre_images = cx.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        vitesse = cx.execute("SELECT valeur FROM meta WHERE cle='secondes_par_image'").fetchone()
        derniere = cx.execute("SELECT valeur FROM meta WHERE cle='derniere_indexation'").fetchone()
        return {
            "fichiers": fichiers - illisibles,  # documents et images
            "images": nombre_images,
            "secondes_par_image": round(float(vitesse[0]), 2) if vitesse else None,
            "illisibles": illisibles,
            "morceaux": morceaux,
            "derniere_indexation": (
                datetime.fromtimestamp(float(derniere[0])).strftime("%d/%m/%Y à %H:%M") if derniere else None
            ),
            "recherche_par_mots": self.mots,
        }

    def illisibles(self, limite: int = 200) -> list[dict]:
        lignes = self._cx().execute(
            "SELECT chemin, erreur FROM fichiers WHERE erreur IS NOT NULL ORDER BY chemin LIMIT ?", (limite,)
        ).fetchall()
        return [{"chemin": chemin, "erreur": erreur} for chemin, erreur in lignes]


def _extrait(texte: str, mots: list[str], longueur: int = 320) -> str:
    """Un bout du passage trouvé, centré si possible sur un mot de la question."""
    plat = " ".join(texte.split())
    if len(plat) <= longueur:
        return plat
    bas = plat.lower()
    position = min((p for p in (bas.find(mot) for mot in mots) if p != -1), default=0)
    debut = max(0, position - longueur // 3)
    if debut:
        espace = plat.find(" ", debut)
        debut = espace + 1 if espace != -1 and espace < position else debut
    fin = min(len(plat), debut + longueur)
    if fin < len(plat):
        espace = plat.rfind(" ", debut, fin)
        fin = espace if espace > debut else fin
    return ("… " if debut else "") + plat[debut:fin] + (" …" if fin < len(plat) else "")
