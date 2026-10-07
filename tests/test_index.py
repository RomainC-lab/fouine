import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fouine.index import Index
from tests import outils
from tests.outils import FauxEmbedding, ecrire, reglages_pour


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(os.path.realpath(self._tmp.name))
        self.docs = base / "Documents"
        self.docs.mkdir()
        self.donnees = base / "donnees"
        self.embedding = FauxEmbedding()
        self.index = Index(self.donnees, self.embedding)
        self.addCleanup(self.index.fermer)
        self.reglages = reglages_pour(self.docs)

    def chemins(self):
        cx = sqlite3.connect(self.index.base)
        try:
            return {os.path.basename(c) for (c,) in cx.execute("SELECT chemin FROM fichiers")}
        finally:
            cx.close()

    def noms(self, question):
        return [r["nom"] for r in self.index.rechercher(question)]


class TestIncremental(Base):
    def test_fichier_inchange_pas_relu(self):
        ecrire(self.docs / "a.txt", "les vacances en Bretagne")
        ecrire(self.docs / "b.txt", "la recette du gâteau")
        bilan = self.index.indexer(self.reglages)
        self.assertEqual((bilan["nouveaux"], bilan["inchanges"]), (2, 0))
        appels = self.embedding.appels
        bilan = self.index.indexer(self.reglages)
        self.assertEqual((bilan["nouveaux"], bilan["modifies"], bilan["inchanges"]), (0, 0, 2))
        self.assertEqual(self.embedding.appels, appels, "aucun calcul refait")

    def test_fichier_modifie_relu(self):
        fichier = ecrire(self.docs / "a.txt", "ancien contenu sur les tulipes")
        ecrire(self.docs / "b.txt", "autre chose")
        self.index.indexer(self.reglages)
        ecrire(fichier, "nouveau contenu sur les orchidées, plus long")
        bilan = self.index.indexer(self.reglages)
        self.assertEqual((bilan["modifies"], bilan["inchanges"]), (1, 1))
        self.assertEqual(self.noms("orchidées"), ["a.txt"])
        self.assertEqual(self.noms("tulipes"), [])

    def test_meme_taille_mais_date_changee(self):
        fichier = ecrire(self.docs / "a.txt", "chat")
        self.index.indexer(self.reglages)
        ecrire(fichier, "pont")
        infos = os.stat(fichier)
        os.utime(fichier, ns=(infos.st_atime_ns, infos.st_mtime_ns + 5_000_000_000))
        self.assertEqual(self.index.indexer(self.reglages)["modifies"], 1)
        self.assertEqual(self.noms("pont"), ["a.txt"])

    def test_fichier_supprime_sort_de_l_index(self):
        ecrire(self.docs / "a.txt", "la tondeuse du voisin")
        ecrire(self.docs / "b.txt", "le vélo rouge")
        self.index.indexer(self.reglages)
        os.remove(self.docs / "a.txt")
        bilan = self.index.indexer(self.reglages)
        self.assertEqual(bilan["retires"], 1)
        self.assertEqual(self.chemins(), {"b.txt"})
        self.assertEqual(self.noms("tondeuse"), [])
        self.assertEqual(self.index.statistiques()["fichiers"], 1)

    def test_fichier_desormais_filtre_sort_de_l_index(self):
        ecrire(self.docs / "a.txt", "texte")
        ecrire(self.docs / "b.md", "texte")
        self.index.indexer(self.reglages)
        self.index.indexer(reglages_pour(self.docs, extensions=[".md"]))
        self.assertEqual(self.chemins(), {"b.md"})

    def test_dossier_debranche_garde(self):
        cle = self.docs.parent / "cle_usb"
        ecrire(cle / "c.txt", "photos de mariage")
        ecrire(self.docs / "a.txt", "texte")
        reglages = reglages_pour(self.docs, cle)
        self.index.indexer(reglages)
        os.rename(cle, self.docs.parent / "ailleurs")
        bilan = self.index.indexer(reglages)
        self.assertEqual(bilan["retires"], 0)
        self.assertEqual(self.chemins(), {"a.txt", "c.txt"})
        # Retiré de la liste des dossiers : cette fois il sort de l'index.
        self.index.indexer(reglages_pour(self.docs))
        self.assertEqual(self.chemins(), {"a.txt"})

    def test_interrompre_puis_reprendre(self):
        for i in range(6):
            ecrire(self.docs / f"f{i}.txt", f"document numéro {i}")
        vus = []

        def progression(**infos):
            if infos["etape"] == "lecture":
                vus.append(infos["fichier"])

        bilan = self.index.indexer(self.reglages, progression=progression, arret=lambda: len(vus) >= 3)
        self.assertTrue(bilan["arrete"])
        faits = len(self.chemins())
        self.assertTrue(0 < faits < 6, faits)
        bilan = self.index.indexer(self.reglages)
        self.assertFalse(bilan["arrete"])
        self.assertEqual((bilan["inchanges"], bilan["nouveaux"]), (faits, 6 - faits))
        self.assertEqual(len(self.chemins()), 6)

    def test_arret_pendant_le_parcours_ne_retire_rien(self):
        ecrire(self.docs / "a.txt", "texte")
        self.index.indexer(self.reglages)
        os.remove(self.docs / "a.txt")
        bilan = self.index.indexer(self.reglages, arret=lambda: True)
        self.assertTrue(bilan["arrete"])
        self.assertEqual(self.chemins(), {"a.txt"})

    def test_fichier_illisible_note_et_pas_retente(self):
        ecrire(self.docs / "casse.pdf", b"%PDF-1.4 abime")
        ecrire(self.docs / "bon.txt", "texte")
        bilan = self.index.indexer(self.reglages)
        self.assertEqual((bilan["nouveaux"], bilan["illisibles"]), (1, 1))
        stats = self.index.statistiques()
        self.assertEqual((stats["fichiers"], stats["illisibles"]), (1, 1))
        self.assertEqual(self.index.illisibles()[0]["chemin"], str(self.docs / "casse.pdf"))
        self.assertEqual(self.index.indexer(self.reglages)["inchanges"], 2)

    def test_fichier_sensible_jamais_envoye_au_modele(self):
        ecrire(self.docs / "mot de passe.txt", "hunter2-ultra-confidentiel")
        ecrire(self.docs / ".env", "CLE=tressecret")
        ecrire(self.docs / "liste.txt", "pain beurre confiture")
        self.index.indexer(self.reglages)
        tout = " ".join(self.embedding.textes_vus)
        self.assertNotIn("hunter2", tout)
        self.assertNotIn("tressecret", tout)
        self.assertEqual(self.chemins(), {"liste.txt"})
        contenu = Path(self.index.base).read_bytes()
        self.assertNotIn(b"hunter2", contenu)

    def test_changement_de_modele_vide_l_index(self):
        ecrire(self.docs / "a.txt", "texte")
        self.index.indexer(self.reglages)
        self.index.fermer()
        autre = FauxEmbedding()
        autre.nom = "autre-modele"
        index = Index(self.donnees, autre)
        self.addCleanup(index.fermer)
        self.assertEqual(index.statistiques()["fichiers"], 0)
        self.assertEqual(index.indexer(self.reglages)["nouveaux"], 1)

    def test_index_garde_apres_fermeture(self):
        ecrire(self.docs / "a.txt", "le chien dort")
        self.index.indexer(self.reglages)
        self.index.fermer()
        index = Index(self.donnees, FauxEmbedding())
        self.addCleanup(index.fermer)
        self.assertEqual([r["nom"] for r in index.rechercher("chien")], ["a.txt"])


class TestRecherche(Base):
    def setUp(self):
        super().setUp()
        ecrire(self.docs / "plombier.txt", "Facture du plombier pour la réparation de la fuite sous l'évier. Total 240 euros.")
        ecrire(self.docs / "recette.md", "Tarte aux pommes : pâte brisée, six pommes, sucre, cannelle. Cuire 40 minutes.")
        outils.docx(self.docs / "mairie.docx", ["Lettre à la mairie pour demander un rendez-vous au service état civil."])
        outils.pdf(self.docs / "assurance.pdf", ["Contrat assurance habitation numero 4521", "Garantie degat des eaux"])
        ecrire(self.docs / "Photos vacances 2019.pdf", b"%PDF-1.4 abime")
        long = "\n\n".join(f"Paragraphe {i} sur le jardin et les tomates." for i in range(80))
        ecrire(self.docs / "jardin.txt", long + "\n\nLe composteur est derrière le cabanon.")
        self.index.indexer(self.reglages)

    def test_mot_exact(self):
        self.assertEqual(self.noms("plombier")[0], "plombier.txt")
        self.assertEqual(self.noms("cannelle")[0], "recette.md")
        self.assertEqual(self.noms("mairie")[0], "mairie.docx")
        self.assertEqual(self.noms("assurance habitation")[0], "assurance.pdf")

    def test_accents_majuscules_et_pluriels(self):
        self.assertEqual(self.noms("REPARATION")[0], "plombier.txt")
        self.assertEqual(self.noms("pomme")[0], "recette.md")
        self.assertEqual(self.noms("dégât")[0], "assurance.pdf")

    def test_phrase_entiere(self):
        self.assertEqual(self.noms("combien a coûté la réparation de la fuite ?")[0], "plombier.txt")

    def test_un_resultat_par_fichier_avec_extrait(self):
        resultats = self.index.rechercher("tomates jardin")
        self.assertEqual([r["nom"] for r in resultats].count("jardin.txt"), 1)
        premier = resultats[0]
        self.assertEqual(premier["nom"], "jardin.txt")
        self.assertEqual(premier["dossier"], str(self.docs))
        self.assertRegex(premier["modifie"], r"^\d\d/\d\d/\d{4}$")
        self.assertIn("tomates", premier["extrait"])
        self.assertLessEqual(len(premier["extrait"]), 330)

    def test_passage_en_fin_de_long_fichier(self):
        resultats = self.index.rechercher("composteur")
        self.assertEqual(resultats[0]["nom"], "jardin.txt")
        self.assertIn("composteur", resultats[0]["extrait"])

    def test_question_vide_ou_bizarre(self):
        self.assertEqual(self.index.rechercher("   "), [])
        for question in ('"', "AND OR NOT", "a* (b", "plombier\" OR \"x", "🙂", "-" * 50, "x" * 5000):
            self.index.rechercher(question)  # ne doit jamais lever d'erreur

    def test_sans_recherche_par_mots(self):
        self.index.mots = False
        self.assertIn("plombier.txt", self.noms("facture plombier fuite"))

    def test_seulement_les_chemins_de_l_index(self):
        identifiant = self.index.rechercher("plombier")[0]["id"]
        self.assertEqual(self.index.chemin(identifiant), str(self.docs / "plombier.txt"))
        for faux in (999999, "1", str(self.docs / "plombier.txt"), None, True, 1.0, [1]):
            self.assertIsNone(self.index.chemin(faux))


class TestNomDeFichier(Base):
    def test_fichier_sans_texte_trouvable_par_son_nom(self):
        ecrire(self.docs / "Carte_grise-voiture.txt", "   ")
        ecrire(self.docs / "autre.txt", "rien à voir")
        self.index.indexer(self.reglages)
        self.assertEqual(self.noms("carte grise")[0], "Carte_grise-voiture.txt")


if __name__ == "__main__":
    unittest.main()
