"""Les images : filtres, lecture sans risque, index, recherche en deux blocs, vignettes.

Tout tourne avec un faux modèle d'images (il ne voit que la couleur moyenne) :
rien n'est téléchargé.
"""

import io
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

import numpy as np
from PIL import Image

from fouine import filtres, images, reglages as mod_reglages
from fouine.extraction import Illisible
from fouine.index import Index
from tests.outils import FauxEmbedding, FauxEmbeddingImages, ecrire, image, reglages_pour
from tests.test_serveur import Base as BaseServeur

ROUGE, VERT, BLEU = (210, 20, 20), (20, 190, 40), (20, 30, 220)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(os.path.realpath(self._tmp.name))
        self.docs = base / "Documents"
        self.docs.mkdir()
        self.donnees = base / "donnees"
        self.embedding = FauxEmbedding()
        self.modele_images = FauxEmbeddingImages()
        self.index = Index(self.donnees, self.embedding, self.modele_images)
        self.addCleanup(self.index.fermer)
        self.reglages = reglages_pour(self.docs, lire_images=True)

    def raisons(self, **changements):
        reglages = dict(self.reglages, **changements)
        return {
            os.path.relpath(e.chemin, self.docs).replace(os.sep, "/"): e.raison
            for e in filtres.parcourir(reglages)
        }

    def lignes(self, requete):
        cx = sqlite3.connect(self.index.base)
        try:
            return cx.execute(requete).fetchall()
        finally:
            cx.close()

    def noms_images(self, question):
        return [r["nom"] for r in self.index.rechercher_images(question)]


class TestFiltresImages(Base):
    def test_option_decochee_par_defaut_et_images_jamais_ouvertes(self):
        self.assertFalse(mod_reglages.reglages_par_defaut()["lire_images"])
        ecrire(self.docs / "photo.jpg", b"ceci n'est pas une image")
        image(self.docs / "vraie.png")
        raisons = self.raisons(lire_images=False)
        self.assertEqual(raisons, {"photo.jpg": filtres.TYPE, "vraie.png": filtres.TYPE})

    def test_types_lus_et_types_non_lus(self):
        for nom in ("a.jpg", "b.JPEG", "c.png", "d.webp", "e.bmp", "f.gif", "g.tif"):
            image(self.docs / nom)
        for nom in ("h.heic", "i.cr2", "j.mp4", "k.svg", "l.psd"):
            ecrire(self.docs / nom, b"x")
        raisons = self.raisons()
        for nom in ("a.jpg", "b.JPEG", "c.png", "d.webp", "e.bmp", "f.gif", "g.tif"):
            self.assertIsNone(raisons[nom], nom)
        for nom in ("h.heic", "i.cr2", "j.mp4", "k.svg", "l.psd"):
            self.assertEqual(raisons[nom], filtres.TYPE, nom)

    def test_icones_et_miniatures_ecartees(self):
        image(self.docs / "icone.png", taille=(32, 32))
        image(self.docs / "bandeau.png", taille=(800, 40))
        image(self.docs / "juste.png", taille=(64, 64))
        raisons = self.raisons()
        self.assertEqual(raisons["icone.png"], filtres.IMAGE_PETITE)
        self.assertEqual(raisons["bandeau.png"], filtres.IMAGE_PETITE)
        self.assertIsNone(raisons["juste.png"])
        self.assertIsNone(self.raisons(image_cote_min_px=16)["icone.png"], "réglable")

    def test_taille_maximale_du_fichier_reglable(self):
        ecrire(self.docs / "gros.bmp", image(self.docs / "gros.bmp", taille=(600, 600)).read_bytes())
        self.assertIsNone(self.raisons()["gros.bmp"])
        self.assertEqual(self.raisons(image_taille_max_mo=0.5)["gros.bmp"], filtres.TROP_GROS)

    def test_image_geante_ecartee_sans_etre_decodee(self):
        image(self.docs / "geante.png", taille=(400, 300))
        ancien = images.PIXELS_MAX
        images.PIXELS_MAX = 100_000
        self.addCleanup(setattr, images, "PIXELS_MAX", ancien)
        self.assertEqual(self.raisons()["geante.png"], filtres.IMAGE_GEANTE)
        with self.assertRaises(Illisible):
            images.ouvrir(str(self.docs / "geante.png"))
        images.PIXELS_MAX = 50_000  # plus du double : Pillow lui-même refuse
        with self.assertRaises(Illisible):
            images.ouvrir(str(self.docs / "geante.png"))

    def test_memes_filtres_que_les_documents(self):
        image(self.docs / "vacances.jpg")
        image(self.docs / "mot de passe wifi.png")
        image(self.docs / ".cachee.png")
        image(self.docs / "node_modules" / "logo.png")
        image(self.docs / ".ssh" / "schema.png")
        image(self.docs / "Google" / "Chrome" / "capture.png")
        raisons = self.raisons()
        self.assertIsNone(raisons["vacances.jpg"])
        self.assertEqual(raisons["mot de passe wifi.png"], filtres.SENSIBLE)
        self.assertEqual(raisons[".cachee.png"], filtres.CACHE)
        self.assertEqual(raisons["node_modules"], filtres.TECHNIQUE)
        self.assertEqual(raisons[".ssh"], filtres.SENSIBLE)
        self.assertEqual(raisons["Google/Chrome"], filtres.SENSIBLE)
        self.assertEqual(self.raisons(inclure_caches=True)[".cachee.png"], None)

    def test_lien_vers_une_image_jamais_suivi(self):
        dehors = image(self.docs.parent / "dehors.png")
        try:
            os.symlink(dehors, self.docs / "raccourci.png")
        except (OSError, NotImplementedError):
            self.skipTest("ce PC ne permet pas de créer un lien symbolique")
        self.assertEqual(self.raisons()["raccourci.png"], filtres.LIEN)

    def test_en_tete_illisible_garde_pour_etre_note(self):
        ecrire(self.docs / "fausse.jpg", "du texte, pas une image")
        self.assertIsNone(self.raisons()["fausse.jpg"])

    def test_image_deja_lue_pas_rouverte_par_le_parcours(self):
        image(self.docs / "a.png")
        self.index.indexer(self.reglages)
        ouvertes = []
        vraie = images.dimensions
        images.dimensions = lambda chemin: ouvertes.append(chemin) or vraie(chemin)
        self.addCleanup(setattr, images, "dimensions", vraie)
        image(self.docs / "b.png")
        self.index.indexer(self.reglages)
        self.assertEqual([os.path.basename(c) for c in ouvertes], ["b.png"])


class TestLectureImages(Base):
    def test_formats_et_transparence(self):
        Image.new("RGBA", (100, 80), (0, 0, 0, 0)).save(self.docs / "vide.png")
        ouverte, origine = images.ouvrir(str(self.docs / "vide.png"))
        self.assertEqual((ouverte.mode, origine), ("RGB", (100, 80)))
        self.assertEqual(ouverte.getpixel((5, 5)), (255, 255, 255), "fond blanc sous la transparence")
        Image.new("P", (90, 70)).save(self.docs / "palette.gif")
        self.assertEqual(images.ouvrir(str(self.docs / "palette.gif"))[0].mode, "RGB")
        Image.new("L", (90, 70), 128).save(self.docs / "gris.jpg")
        self.assertEqual(images.ouvrir(str(self.docs / "gris.jpg"))[0].mode, "RGB")

    def test_gif_anime_premiere_image(self):
        vues = [Image.new("RGB", (120, 90), couleur) for couleur in (ROUGE, BLEU, VERT)]
        vues[0].save(self.docs / "anime.gif", save_all=True, append_images=vues[1:], duration=100)
        ouverte, _ = images.ouvrir(str(self.docs / "anime.gif"))
        rouge, vert, bleu = ouverte.getpixel((10, 10))
        self.assertTrue(rouge > 150 and vert < 80 and bleu < 80)

    def test_grande_photo_reduite_des_l_ouverture(self):
        image(self.docs / "grande.jpg", taille=(4000, 3000))
        ouverte, origine = images.ouvrir(str(self.docs / "grande.jpg"))
        self.assertEqual(origine, (4000, 3000))
        self.assertLess(ouverte.width, 4000)
        self.assertGreaterEqual(ouverte.width, 1024)

    def test_images_abimees(self):
        entiere = image(self.docs / "entiere.jpg", taille=(600, 400)).read_bytes()
        ecrire(self.docs / "tronquee.jpg", entiere[: len(entiere) // 3])
        ecrire(self.docs / "fausse.png", "bonjour")
        ecrire(self.docs / "vide.webp", b"")
        for nom in ("tronquee.jpg", "fausse.png", "vide.webp", "absente.png"):
            with self.assertRaises(Illisible, msg=nom):
                images.ouvrir(str(self.docs / nom))

    def test_preparation_pour_le_modele(self):
        maximum = images.JETONS_PAR_IMAGE * 9
        for taille in ((640, 480), (480, 640), (64, 64), (3000, 64), (64, 3000), (1000, 1000)):
            patchs, positions, jetons = images.preparer(Image.new("RGB", taille, ROUGE))
            self.assertEqual(patchs.shape[1], 16 * 16 * 3, taille)
            self.assertEqual(positions.shape, (patchs.shape[0], 2), taille)
            self.assertLessEqual(patchs.shape[0], maximum, taille)
            self.assertEqual(patchs.shape[0], jetons * 9, taille)
            self.assertGreaterEqual(jetons, 1, taille)
            self.assertEqual(patchs.dtype, np.float32)
            self.assertLessEqual(float(patchs.max()), 1.0)

    def test_vecteurs_raccourcis_et_de_longueur_1(self):
        courts = images.raccourcir(np.random.default_rng(0).normal(size=(3, 768)))
        self.assertEqual(courts.shape, (3, images.DIMENSION_IMAGES))
        np.testing.assert_allclose(np.linalg.norm(courts, axis=1), 1.0, rtol=1e-5)


class TestIndexImages(Base):
    def setUp(self):
        super().setUp()
        image(self.docs / "tomate.jpg", ROUGE)
        image(self.docs / "pelouse.png", VERT)
        image(self.docs / "mer.webp", BLEU, lossless=True)
        ecrire(self.docs / "plombier.txt", "Facture du plombier pour la fuite")

    def test_option_decochee_second_modele_jamais_charge(self):
        bilan = self.index.indexer(dict(self.reglages, lire_images=False))
        self.assertEqual((bilan["nouveaux"], bilan["images"]), (1, 0))
        self.assertEqual(self.index.rechercher_images("rouge"), [])
        self.assertEqual(self.index.statistiques()["images"], 0)
        self.assertEqual(self.modele_images.chargements, 0)
        self.assertFalse(self.index.vignettes.exists())

    def test_inchange_pas_relu_modifie_relu_supprime_sorti(self):
        bilan = self.index.indexer(self.reglages)
        self.assertEqual((bilan["nouveaux"], bilan["images"], bilan["illisibles"]), (4, 3, 0))
        self.assertEqual(self.modele_images.images_vues, 3)
        bilan = self.index.indexer(self.reglages)
        self.assertEqual((bilan["nouveaux"], bilan["modifies"], bilan["inchanges"]), (0, 0, 4))
        self.assertEqual(self.modele_images.images_vues, 3, "aucune image relue")

        image(self.docs / "tomate.jpg", BLEU, taille=(330, 250))
        bilan = self.index.indexer(self.reglages)
        self.assertEqual((bilan["modifies"], bilan["inchanges"]), (1, 3))
        self.assertEqual(self.modele_images.images_vues, 4)
        self.assertIn("tomate.jpg", self.noms_images("bleu")[:2])

        vignettes = set(os.listdir(self.index.vignettes))
        self.assertEqual(len(vignettes), 3)
        (self.docs / "mer.webp").unlink()
        bilan = self.index.indexer(self.reglages)
        self.assertEqual(bilan["retires"], 1)
        self.assertNotIn("mer.webp", self.noms_images("bleu"))
        self.assertEqual(len(os.listdir(self.index.vignettes)), 2, "la vignette part avec l'image")

    def test_option_decochee_ensuite_les_images_sortent(self):
        self.index.indexer(self.reglages)
        bilan = self.index.indexer(dict(self.reglages, lire_images=False))
        self.assertEqual((bilan["retires"], bilan["inchanges"]), (3, 1))
        self.assertEqual(self.index.statistiques()["images"], 0)
        self.assertEqual(os.listdir(self.index.vignettes), [])

    def test_interrompre_puis_reprendre(self):
        etat = {"arret": False}

        def progression(**infos):
            if infos["etape"] == "lecture" and infos["fait"] >= 2:
                etat["arret"] = True

        bilan = self.index.indexer(self.reglages, progression=progression, arret=lambda: etat["arret"])
        self.assertTrue(bilan["arrete"])
        faits = self.index.statistiques()["fichiers"]
        self.assertTrue(0 < faits < 4)
        vues = self.modele_images.images_vues
        bilan = self.index.indexer(self.reglages)
        self.assertFalse(bilan["arrete"])
        self.assertEqual(bilan["inchanges"], faits)
        self.assertEqual(self.index.statistiques()["fichiers"], 4)
        self.assertEqual(self.modele_images.images_vues, vues + (4 - faits))

    def test_documents_lus_avant_les_images(self):
        ecrire(self.docs / "zebre.txt", "le zèbre")
        ordre = []
        self.index.indexer(self.reglages, progression=lambda **i: i["fichier"] and ordre.append(i["fichier"]))
        genres = [images.est_image(chemin) for chemin in ordre]
        self.assertEqual(genres, sorted(genres))

    def test_image_illisible_notee_jamais_un_plantage(self):
        entiere = (self.docs / "tomate.jpg").read_bytes()
        ecrire(self.docs / "tronquee.jpg", image(self.docs / "tronquee.jpg", taille=(900, 700)).read_bytes()[:400])
        ecrire(self.docs / "fausse.png", "pas une image")
        self.assertGreater(len(entiere), 400)
        bilan = self.index.indexer(self.reglages)
        self.assertEqual((bilan["nouveaux"], bilan["illisibles"]), (4, 2))
        illisibles = {os.path.basename(i["chemin"]): i["erreur"] for i in self.index.illisibles()}
        self.assertEqual(set(illisibles), {"tronquee.jpg", "fausse.png"})
        self.assertEqual(self.index.statistiques()["images"], 3)
        vues = self.modele_images.images_vues
        bilan = self.index.indexer(self.reglages)
        self.assertEqual(bilan["inchanges"], 6, "pas retentée tant que le fichier ne change pas")
        self.assertEqual(self.modele_images.images_vues, vues)

    def test_image_que_le_modele_refuse(self):
        def casse(image):
            raise RuntimeError("erreur interne du modèle")

        self.modele_images.vecteur_image = casse
        bilan = self.index.indexer(self.reglages)
        self.assertEqual((bilan["nouveaux"], bilan["illisibles"]), (1, 3))
        self.assertNotIn("erreur interne", str(self.index.illisibles()))

    def test_dossier_de_fouine_jamais_lu_meme_dans_un_dossier_choisi(self):
        reglages = dict(self.reglages, dossiers=[str(self.docs.parent)])
        self.index.indexer(reglages)
        self.assertEqual(len(os.listdir(self.index.vignettes)), 3)
        bilan = self.index.indexer(reglages)
        self.assertEqual((bilan["nouveaux"], bilan["inchanges"]), (0, 4), "les vignettes ne sont pas prises pour des photos")
        apercu = filtres.apercu(reglages, dossier_fouine=self.donnees)
        self.assertEqual(apercu["acceptes"]["nombre"], 4)

    def test_image_sensible_jamais_envoyee_au_modele(self):
        image(self.docs / "carte secrete.png", BLEU)
        self.index.indexer(self.reglages)
        self.assertEqual(self.modele_images.images_vues, 3)
        self.assertNotIn("carte secrete.png", self.noms_images("bleu"))

    def test_deux_blocs_separes(self):
        self.index.indexer(self.reglages)
        documents = self.index.rechercher("facture plombier rouge")
        self.assertEqual([r["nom"] for r in documents], ["plombier.txt"], "aucune image parmi les documents")
        trouvees = self.index.rechercher_images("une chose rouge")
        self.assertEqual(trouvees[0]["nom"], "tomate.jpg")
        self.assertEqual({r["nom"] for r in trouvees}, {"tomate.jpg", "pelouse.png", "mer.webp"})
        scores = [r["score"] for r in trouvees]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual((trouvees[0]["largeur"], trouvees[0]["hauteur"]), (320, 240))
        self.assertEqual(self.noms_images("vert")[0], "pelouse.png")
        self.assertEqual(self.index.rechercher_images("   "), [])

    def test_nombre_d_images_montrees_limite(self):
        for numero in range(20):
            image(self.docs / f"serie{numero:02}.png", (numero * 10, 0, 250 - numero * 10))
        self.index.indexer(self.reglages)
        self.assertEqual(len(self.index.rechercher_images("rouge")), 12)

    def test_vitesse_mesuree_seulement_avec_assez_d_images(self):
        (self.docs / "mer.webp").unlink()
        self.index.indexer(self.reglages)
        self.assertIsNone(self.index.statistiques()["secondes_par_image"], "deux images : rien de promis")
        restes = []
        for numero in range(5):
            image(self.docs / f"n{numero}.png", BLEU)
        self.index.indexer(self.reglages, progression=lambda **infos: restes.append(infos.get("reste_s")))
        self.assertIsNotNone(self.index.statistiques()["secondes_par_image"])
        self.assertIsNone(restes[1], "pas d'estimation avant trois images mesurées")
        self.assertTrue(any(reste is not None for reste in restes))

    def test_changer_le_modele_des_images_garde_les_documents(self):
        self.index.indexer(self.reglages)
        self.index.fermer()
        autre = FauxEmbeddingImages()
        autre.nom = "autre-modele-images"
        index = Index(self.donnees, self.embedding, autre)
        self.addCleanup(index.fermer)
        self.assertEqual(index.statistiques()["images"], 0)
        self.assertEqual([r["nom"] for r in index.rechercher("plombier")], ["plombier.txt"])
        self.assertEqual(os.listdir(index.vignettes), [])

    def test_changer_le_modele_des_textes_garde_les_images(self):
        self.index.indexer(self.reglages)
        self.index.fermer()
        autre = FauxEmbedding()
        autre.nom = "autre-modele"
        index = Index(self.donnees, autre, self.modele_images)
        self.addCleanup(index.fermer)
        self.assertEqual(index.statistiques()["images"], 3)
        self.assertEqual(index.rechercher("plombier"), [])


class TestMigration(unittest.TestCase):
    """Un index créé par Fouine 0.2.0 continue de marcher, sans tout relire."""

    SCHEMA_0_2 = """
    CREATE TABLE meta (cle TEXT PRIMARY KEY, valeur TEXT);
    CREATE TABLE fichiers (id INTEGER PRIMARY KEY, chemin TEXT NOT NULL UNIQUE, taille INTEGER NOT NULL,
        modifie INTEGER NOT NULL, erreur TEXT, indexe_le REAL NOT NULL);
    CREATE TABLE morceaux (id INTEGER PRIMARY KEY, fichier_id INTEGER NOT NULL REFERENCES fichiers(id) ON DELETE CASCADE,
        rang INTEGER NOT NULL, texte TEXT NOT NULL, vecteur BLOB NOT NULL);
    CREATE INDEX morceaux_par_fichier ON morceaux(fichier_id);
    """

    def test_index_0_2_garde(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(os.path.realpath(tmp.name))
        docs, donnees = base / "Documents", base / "donnees"
        fichier = ecrire(docs / "plombier.txt", "Facture du plombier pour la fuite")
        image(docs / "tomate.jpg", ROUGE)
        donnees.mkdir()
        embedding = FauxEmbedding()
        infos = os.stat(fichier)
        cx = sqlite3.connect(donnees / "index.sqlite")
        cx.executescript(self.SCHEMA_0_2)
        cx.execute("INSERT INTO meta VALUES ('modele', ?)", (embedding.nom,))
        cx.execute(
            "INSERT INTO fichiers VALUES (1, ?, ?, ?, NULL, 0)", (str(fichier), infos.st_size, infos.st_mtime_ns)
        )
        vecteur = embedding.vecteurs(["plombier\nFacture du plombier pour la fuite"])[0]
        cx.execute("INSERT INTO morceaux VALUES (1, 1, 0, 'Facture du plombier pour la fuite', ?)", (vecteur.tobytes(),))
        cx.commit()
        cx.close()
        appels = embedding.appels

        modele_images = FauxEmbeddingImages()
        index = Index(donnees, embedding, modele_images)
        self.addCleanup(index.fermer)
        self.assertEqual([r["nom"] for r in index.rechercher("facture du plombier")], ["plombier.txt"])
        self.assertEqual(index.statistiques()["fichiers"], 1)
        bilan = index.indexer(reglages_pour(docs))
        self.assertEqual((bilan["inchanges"], bilan["nouveaux"]), (1, 0), "rien n'est relu")
        self.assertEqual(embedding.appels, appels + 1, "seule la question a été calculée")
        bilan = index.indexer(reglages_pour(docs, lire_images=True))
        self.assertEqual((bilan["inchanges"], bilan["nouveaux"], bilan["images"]), (1, 1, 1))
        self.assertEqual([r["nom"] for r in index.rechercher_images("rouge")], ["tomate.jpg"])
        self.assertEqual(index.chemin(1), str(fichier))

    def test_anciens_reglages_completes(self):
        anciens = {"dossiers": ["/quelque/part"], "extensions": [".txt"], "taille_max_mo": 20}
        propre = mod_reglages.nettoyer(anciens)
        self.assertFalse(propre["lire_images"])
        self.assertEqual(propre["image_cote_min_px"], mod_reglages.IMAGE_COTE_MIN_PX)
        self.assertEqual(propre["image_taille_max_mo"], mod_reglages.IMAGE_TAILLE_MAX_MO)
        farfelu = mod_reglages.nettoyer({"lire_images": "oui", "image_cote_min_px": -3, "image_taille_max_mo": "x"})
        self.assertFalse(farfelu["lire_images"])
        self.assertEqual(farfelu["image_cote_min_px"], mod_reglages.IMAGE_COTE_MIN_PX)


class TestServeurImages(BaseServeur):
    def setUp(self):
        super().setUp()
        image(self.docs / "tomate.jpg", ROUGE, taille=(1200, 900))
        image(self.docs / "mer.png", BLEU)
        image(self.docs / "mot de passe.png", VERT)
        image(self.dehors.parent / "dehors.png", VERT)
        mod_reglages.enregistrer(reglages_pour(self.docs, lire_images=True), self.donnees)

    def vignette(self, identifiant, **options):
        return self.demander("GET", f"/api/vignette?id={identifiant}", **options)

    def test_recherche_en_deux_blocs(self):
        _, apercu = self.api("apercu")
        self.assertEqual((apercu["acceptes"]["nombre"], apercu["acceptes"]["images"]), (3, 2))
        self.assertEqual(apercu["acceptes"]["images_a_lire"], 2)
        self.assertIsNone(apercu["duree_images_s"], "vitesse pas encore mesurée : aucune durée promise")
        etat = self.indexer()
        self.assertEqual((etat["index"]["fichiers"], etat["index"]["images"]), (3, 2))
        self.assertEqual(etat["tache"]["bilan"]["images"], 2)
        _, documents = self.api("recherche", {"question": "plombier rouge"})
        self.assertEqual([r["nom"] for r in documents["resultats"]], ["plombier.txt"])
        self.assertNotIn("images", documents)
        _, trouvees = self.api("recherche_images", {"question": "rouge"})
        self.assertEqual([r["nom"] for r in trouvees["images"]], ["tomate.jpg", "mer.png"])
        reponse, _ = self.api("recherche_images", {"question": 3})
        self.assertEqual(reponse.status, 400)
        _, apercu = self.api("apercu")
        self.assertEqual(apercu["acceptes"]["images_a_lire"], 0, "déjà lues")

    def test_duree_annoncee_une_fois_la_vitesse_mesuree(self):
        for numero in range(3):
            image(self.docs / f"n{numero}.png", BLEU)
        self.indexer()
        image(self.docs / "nouvelle.png", BLEU)
        _, apercu = self.api("apercu")
        self.assertEqual(apercu["acceptes"]["images_a_lire"], 1)
        self.assertIsInstance(apercu["duree_images_s"], int)

    def test_vignette_petite_et_protegee(self):
        self.indexer()
        _, trouvees = self.api("recherche_images", {"question": "rouge"})
        identifiant = trouvees["images"][0]["id"]
        reponse, contenu = self.vignette(identifiant)
        self.assertEqual(reponse.status, 200)
        self.assertEqual(reponse.getheader("Content-Type"), "image/jpeg")
        self.assertEqual(reponse.getheader("X-Content-Type-Options"), "nosniff")
        self.assertEqual(reponse.getheader("Cache-Control"), "no-store")
        petite = Image.open(io.BytesIO(contenu))
        self.assertEqual(petite.format, "JPEG")
        self.assertLessEqual(max(petite.size), images.COTE_VIGNETTE)
        self.assertLess(len(contenu), (self.docs / "tomate.jpg").stat().st_size)

        for jeton in (False, "faux", self.serveur.jeton[:-1]):
            reponse, _ = self.vignette(identifiant, jeton=jeton)
            self.assertEqual(reponse.status, 403)
        reponse, _ = self.vignette(identifiant, hote="evil.example")
        self.assertEqual(reponse.status, 403)
        reponse, _ = self.vignette(identifiant, entetes={"Origin": "https://evil.example"})
        self.assertEqual(reponse.status, 403)
        reponse, _ = self.vignette(identifiant, entetes={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(reponse.status, 403)
        reponse, _ = self.demander("GET", f"/api/vignette?id={identifiant}&jeton={self.serveur.jeton}", jeton=False)
        self.assertEqual(reponse.status, 403, "le jeton ne passe jamais par l'adresse")

    def test_vignette_seulement_pour_une_image_de_l_index(self):
        self.indexer()
        _, documents = self.api("recherche", {"question": "plombier"})
        texte = documents["resultats"][0]["id"]
        reponse, _ = self.vignette(texte)
        self.assertEqual(reponse.status, 404, "un document n'a pas de vignette")
        reponse, _ = self.vignette(99999)
        self.assertEqual(reponse.status, 404)
        dehors = str(self.dehors.parent / "dehors.png")
        for demande in ("", "abc", "-1", "1.5", "1e3", "../1", "%2e%2e%2f1", "١", dehors, "0x10", "1" * 40, " 1"):
            reponse, _ = self.demander("GET", "/api/vignette?id=" + quote(demande, safe=""))
            self.assertIn(reponse.status, (400, 404), demande)
        reponse, _ = self.demander("GET", "/api/vignette?chemin=" + dehors)
        self.assertEqual(reponse.status, 400)
        for chemin in ("/vignettes/1.jpg", "/api/vignette/1", "/api/vignettes?id=1", "/donnees/vignettes/1.jpg"):
            reponse, _ = self.demander("GET", chemin)
            self.assertEqual(reponse.status, 404, chemin)
        reponse, _ = self.demander("POST", "/api/vignette", {"id": 1})
        self.assertEqual(reponse.status, 404)
        cx = sqlite3.connect(self.index.base)
        try:
            noms = {os.path.basename(c) for (c,) in cx.execute("SELECT chemin FROM fichiers")}
        finally:
            cx.close()
        self.assertEqual(noms, {"plombier.txt", "tomate.jpg", "mer.png"}, "ni l'image sensible, ni celle du dehors")

    def test_vignette_refaite_si_le_cache_a_disparu_et_retiree_avec_l_image(self):
        self.indexer()
        _, trouvees = self.api("recherche_images", {"question": "bleu"})
        identifiant = trouvees["images"][0]["id"]
        for fichier in os.listdir(self.index.vignettes):
            os.unlink(self.index.vignettes / fichier)
        reponse, _ = self.vignette(identifiant)
        self.assertEqual(reponse.status, 200)
        for fichier in os.listdir(self.index.vignettes):
            os.unlink(self.index.vignettes / fichier)
        (self.docs / "mer.png").unlink()
        reponse, _ = self.vignette(identifiant)
        self.assertEqual(reponse.status, 404, "image disparue et pas de cache : rien à montrer")
        self.indexer()
        reponse, _ = self.vignette(identifiant)
        self.assertEqual(reponse.status, 404)

    def test_ouvrir_une_image_de_l_index(self):
        self.indexer()
        _, trouvees = self.api("recherche_images", {"question": "rouge"})
        reponse, _ = self.api("ouvrir", {"id": trouvees["images"][0]["id"], "quoi": "fichier"})
        self.assertEqual(reponse.status, 200)
        self.assertEqual(self.ouvertures, [(str(self.docs / "tomate.jpg"), "fichier")])

    def test_politique_de_securite_au_plus_juste(self):
        reponse, _ = self.demander("GET", "/", jeton=False)
        politique = dict(
            regle.strip().split(" ", 1) for regle in reponse.getheader("Content-Security-Policy").split(";")
        )
        self.assertEqual(politique["img-src"], "'self' data: blob:")
        self.assertEqual(politique["default-src"], "'none'")
        self.assertEqual(politique["connect-src"], "'self'")
        self.assertEqual(politique["script-src"], "'self'")
        self.assertNotIn("http", reponse.getheader("Content-Security-Policy"))
        self.assertNotIn("*", reponse.getheader("Content-Security-Policy"))

    def test_remettre_les_filtres_garde_le_choix_des_images(self):
        _, corps = self.api("enregistrer", {"reglages": dict(reglages_pour(self.docs, lire_images=True), image_cote_min_px=200)})
        self.assertEqual(corps["reglages"]["image_cote_min_px"], 200)
        _, corps = self.api("enregistrer", {"reglages": {"defaut": True}})
        self.assertTrue(corps["reglages"]["lire_images"])
        self.assertEqual(corps["reglages"]["image_cote_min_px"], mod_reglages.IMAGE_COTE_MIN_PX)


if __name__ == "__main__":
    unittest.main()
