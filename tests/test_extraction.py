import tempfile
import unittest
from pathlib import Path

from fouine.extraction import Illisible, decouper, extraire
from tests import outils


class TestExtraction(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.d = Path(self._tmp.name)

    def test_texte_utf8_avec_accents(self):
        chemin = outils.ecrire(self.d / "a.txt", "\ufeffÉté à la plage\r\n\r\n\r\n\r\nœufs   brouillés")
        self.assertEqual(extraire(str(chemin)), "Été à la plage\n\nœufs brouillés")

    def test_texte_windows_ancien(self):
        chemin = outils.ecrire(self.d / "a.txt", "déjà reçu, coût 12 €".encode("cp1252"))
        self.assertEqual(extraire(str(chemin)), "déjà reçu, coût 12 €")

    def test_texte_utf16(self):
        chemin = outils.ecrire(self.d / "a.txt", "café crème".encode("utf-16"))
        self.assertEqual(extraire(str(chemin)), "café crème")

    def test_binaire_deguise_en_texte(self):
        chemin = outils.ecrire(self.d / "a.txt", b"\x00\x01\x02\x03PNG\x00\x00")
        with self.assertRaises(Illisible):
            extraire(str(chemin))

    def test_html_sans_scripts_ni_styles(self):
        chemin = outils.ecrire(
            self.d / "a.html",
            "<html><head><title>Ma page</title><style>p{color:red}</style></head><body>"
            "<script>alert('pirate')</script><h1>Recette</h1><p>Tarte aux&nbsp;pommes &amp; cannelle</p></body></html>",
        )
        texte = extraire(str(chemin))
        self.assertIn("Ma page", texte)
        self.assertIn("Recette", texte)
        self.assertIn("Tarte aux pommes & cannelle", texte)
        self.assertNotIn("pirate", texte)
        self.assertNotIn("color", texte)

    def test_pdf(self):
        chemin = outils.pdf(self.d / "a.pdf", ["Facture du plombier", "Total 240 euros"])
        texte = extraire(str(chemin))
        self.assertIn("Facture du plombier", texte)
        self.assertIn("240 euros", texte)

    def test_pdf_abime(self):
        chemin = outils.ecrire(self.d / "a.pdf", b"%PDF-1.4 ceci n'est pas un vrai pdf")
        with self.assertRaises(Illisible):
            extraire(str(chemin))

    def test_word(self):
        chemin = outils.docx(self.d / "a.docx", ["Lettre à la mairie", "Demande de rendez-vous"])
        self.assertEqual(extraire(str(chemin)), "Lettre à la mairie\nDemande de rendez-vous")

    def test_powerpoint_dans_l_ordre_des_diapos(self):
        diapos = [[f"Diapo {n}"] for n in range(1, 12)]
        texte = extraire(str(outils.pptx(self.d / "a.pptx", diapos)))
        self.assertLess(texte.index("Diapo 2"), texte.index("Diapo 10"))
        self.assertIn("Diapo 11", texte)

    def test_excel(self):
        texte = extraire(str(outils.xlsx(self.d / "a.xlsx", ["Loyer", "Électricité"], feuille="Budget 2026")))
        self.assertEqual(texte, "Budget 2026\nLoyer\nÉlectricité")

    def test_libreoffice(self):
        chemin = outils.odt(self.d / "a.odt", ["Compte rendu", "Réunion du lundi"])
        self.assertEqual(extraire(str(chemin)), "Compte rendu\nRéunion du lundi")

    def test_faux_document_office(self):
        chemin = outils.ecrire(self.d / "a.docx", b"pas un zip")
        with self.assertRaises(Illisible):
            extraire(str(chemin))
        chemin = outils._zip(self.d / "b.docx", {"autre.xml": "<a/>"})
        with self.assertRaises(Illisible):
            extraire(str(chemin))

    def test_document_piege_refuse(self):
        piege = '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaa">]><d>&a;</d>'
        chemin = outils._zip(self.d / "a.docx", {"word/document.xml": piege})
        with self.assertRaises(Illisible):
            extraire(str(chemin))

    def test_fichier_disparu(self):
        with self.assertRaises(Illisible):
            extraire(str(self.d / "absent.txt"))


class TestDecoupage(unittest.TestCase):
    def test_texte_court_en_un_morceau(self):
        self.assertEqual(decouper("  Bonjour.  "), ["Bonjour."])
        self.assertEqual(decouper("   "), [])

    def test_recouvrement_et_rien_de_perdu(self):
        mots = [f"mot{i}" for i in range(2000)]
        morceaux = decouper(" ".join(mots), taille=300, recouvrement=60)
        self.assertGreater(len(morceaux), 10)
        self.assertTrue(all(len(m) <= 300 for m in morceaux))
        vus = set()
        for avant, apres in zip(morceaux, morceaux[1:]):
            self.assertTrue(set(avant.split()) & set(apres.split()), "deux morceaux voisins se chevauchent")
        for morceau in morceaux:
            vus.update(morceau.split())
        self.assertEqual(vus, set(mots))
        self.assertTrue(all(m.split()[0] in vus and m.split()[-1] in vus for m in morceaux), "pas de mot coupé")

    def test_coupe_aux_paragraphes(self):
        texte = ("Phrase un. " * 20).strip() + "\n\n" + ("Phrase deux. " * 20).strip()
        morceaux = decouper(texte, taille=260, recouvrement=40)
        self.assertTrue(morceaux[0].endswith("un."))

    def test_texte_sans_espace_termine(self):
        morceaux = decouper("a" * 5000, taille=700, recouvrement=120)
        self.assertGreater(len(morceaux), 5)
        self.assertLess(len(morceaux), 20)


if __name__ == "__main__":
    unittest.main()
