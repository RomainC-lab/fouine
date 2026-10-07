import os
import sys
import tempfile
import unittest
from pathlib import Path

from fouine import filtres, reglages
from tests.outils import ecrire, reglages_pour


class Arbre(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.racine = Path(os.path.realpath(self._tmp.name)) / "Documents"
        self.racine.mkdir()

    def raisons(self, **changements):
        """{chemin relatif: raison} pour tout ce que le parcours a vu."""
        regl = reglages_pour(self.racine, **changements)
        return {
            os.path.relpath(e.chemin, self.racine).replace(os.sep, "/"): e.raison for e in filtres.parcourir(regl)
        }


class TestFiltres(Arbre):
    def test_documents_acceptes(self):
        for nom in ("notes.txt", "Rapport.PDF", "sous/dossier/lettre.docx", "tableau.xlsx", "page.html"):
            ecrire(self.racine / nom)
        vus = self.raisons()
        self.assertEqual(
            {c for c, r in vus.items() if r is None},
            {"notes.txt", "Rapport.PDF", "sous/dossier/lettre.docx", "tableau.xlsx", "page.html"},
        )

    def test_medias_archives_et_programmes_ecartes(self):
        for nom in ("photo.jpg", "film.mp4", "chanson.mp3", "sauvegarde.zip", "jeu.exe", "base.sqlite", "sans_extension"):
            ecrire(self.racine / nom)
        vus = self.raisons()
        self.assertEqual(set(vus.values()), {filtres.TYPE})
        self.assertEqual(len(vus), 7)

    def test_fichiers_sensibles_jamais_lus(self):
        sensibles = [
            ".env", ".env.local", "cle.pem", "serveur.key", "id_rsa", "id_rsa.pub", "id_ed25519", "coffre.kdbx",
            "certificat.pfx", "certificat.p12", "wallet.dat", "Mes mots de passe.txt", "mot de passe wifi.docx",
            "MDP banque.txt", "passwords.csv", "secrets.md", "mon_portefeuille.txt", "identifiants.txt",
        ]
        for nom in sensibles:
            ecrire(self.racine / nom)
        ecrire(self.racine / "normal.txt")
        vus = self.raisons()
        for nom in sensibles:
            self.assertEqual(vus[nom], filtres.SENSIBLE, nom)
        self.assertIsNone(vus["normal.txt"])

    def test_sensible_meme_si_les_caches_sont_inclus(self):
        ecrire(self.racine / ".env")
        ecrire(self.racine / ".ssh" / "config.txt")
        ecrire(self.racine / ".notes" / "idee.txt")
        vus = self.raisons(inclure_caches=True)
        self.assertEqual(vus[".env"], filtres.SENSIBLE)
        self.assertEqual(vus[".ssh"], filtres.SENSIBLE)
        self.assertIsNone(vus[".notes/idee.txt"])

    def test_dossiers_sensibles_pas_ouverts(self):
        ecrire(self.racine / ".ssh" / "known_hosts.txt")
        ecrire(self.racine / ".gnupg" / "notes.txt")
        ecrire(self.racine / "Mots de passe" / "liste.txt")
        ecrire(self.racine / "Sauvegarde" / "Google" / "Chrome" / "User Data" / "historique.txt")
        ecrire(self.racine / "Sauvegarde" / "Mozilla" / "Firefox" / "Profiles" / "abc" / "notes.txt")
        vus = self.raisons(inclure_caches=True)
        self.assertEqual(vus[".ssh"], filtres.SENSIBLE)
        self.assertEqual(vus[".gnupg"], filtres.SENSIBLE)
        self.assertEqual(vus["Mots de passe"], filtres.SENSIBLE)
        self.assertEqual(vus["Sauvegarde/Google/Chrome"], filtres.SENSIBLE)
        self.assertEqual(vus["Sauvegarde/Mozilla/Firefox"], filtres.SENSIBLE)
        self.assertFalse([c for c in vus if c.endswith(".txt")], "rien n'est vu à l'intérieur")

    def test_dossier_voisin_au_nom_proche_non_touche(self):
        # « Chrome » seul, hors d'un dossier « Google », n'est pas un profil de navigateur.
        ecrire(self.racine / "Chrome" / "notice.txt")
        ecrire(self.racine / "Safari au Kenya" / "journal.txt")
        vus = self.raisons()
        self.assertIsNone(vus["Chrome/notice.txt"])
        self.assertIsNone(vus["Safari au Kenya/journal.txt"])

    def test_dossiers_systeme_techniques_et_caches(self):
        ecrire(self.racine / "Windows" / "System32" / "lisezmoi.txt")
        ecrire(self.racine / "AppData" / "Local" / "truc.txt")
        ecrire(self.racine / "$Recycle.Bin" / "vieux.txt")
        ecrire(self.racine / "projet" / "node_modules" / "paquet" / "README.md")
        ecrire(self.racine / "projet" / ".git" / "description.txt")
        ecrire(self.racine / "projet" / "venv" / "notes.txt")
        ecrire(self.racine / "projet" / "__pycache__" / "x.txt")
        ecrire(self.racine / ".cache_perso" / "x.txt")
        ecrire(self.racine / ".cache.txt")
        ecrire(self.racine / "projet" / "LISEZMOI.md")
        vus = self.raisons()
        self.assertEqual(vus["Windows"], filtres.SYSTEME)
        self.assertEqual(vus["AppData"], filtres.SYSTEME)
        self.assertEqual(vus["$Recycle.Bin"], filtres.SYSTEME)
        self.assertEqual(vus["projet/node_modules"], filtres.TECHNIQUE)
        self.assertEqual(vus["projet/.git"], filtres.TECHNIQUE)
        self.assertEqual(vus["projet/venv"], filtres.TECHNIQUE)
        self.assertEqual(vus["projet/__pycache__"], filtres.TECHNIQUE)
        self.assertEqual(vus[".cache_perso"], filtres.CACHE)
        self.assertEqual(vus[".cache.txt"], filtres.CACHE)
        self.assertEqual([c for c, r in vus.items() if r is None], ["projet/LISEZMOI.md"])

    def test_noms_compares_sans_majuscules(self):
        ecrire(self.racine / "NODE_MODULES" / "a.txt")
        ecrire(self.racine / "ID_RSA")
        ecrire(self.racine / "PASSWORD.TXT")
        vus = self.raisons()
        self.assertEqual(vus["NODE_MODULES"], filtres.TECHNIQUE)
        self.assertEqual(vus["ID_RSA"], filtres.SENSIBLE)
        self.assertEqual(vus["PASSWORD.TXT"], filtres.SENSIBLE)

    def test_limite_de_taille(self):
        ecrire(self.racine / "petit.txt", "a" * 1000)
        ecrire(self.racine / "gros.txt", "a" * (2 * 1024 * 1024))
        vus = self.raisons(taille_max_mo=1)
        self.assertIsNone(vus["petit.txt"])
        self.assertEqual(vus["gros.txt"], filtres.TROP_GROS)

    def test_reglages_modifiables(self):
        ecrire(self.racine / "journal.log")
        ecrire(self.racine / "notes.txt")
        ecrire(self.racine / "Archives" / "vieux.txt")
        vus = self.raisons(extensions=[".log"], dossiers_exclus=["archives"])
        self.assertIsNone(vus["journal.log"])
        self.assertEqual(vus["notes.txt"], filtres.TYPE)
        self.assertEqual(vus["Archives"], filtres.TECHNIQUE)

    @unittest.skipIf(sys.platform == "win32", "créer un lien demande des droits particuliers sous Windows")
    def test_liens_symboliques_jamais_suivis(self):
        dehors = self.racine.parent / "Ailleurs"
        ecrire(dehors / "prive.txt", "ne doit pas être lu")
        ecrire(self.racine / "vrai.txt")
        os.symlink(dehors, self.racine / "lien_dossier")
        os.symlink(dehors / "prive.txt", self.racine / "lien_fichier.txt")
        os.symlink(self.racine, self.racine / "boucle")
        os.symlink(self.racine / "absent.txt", self.racine / "casse.txt")
        vus = self.raisons()
        self.assertEqual(vus["lien_dossier"], filtres.LIEN)
        self.assertEqual(vus["lien_fichier.txt"], filtres.LIEN)
        self.assertEqual(vus["boucle"], filtres.LIEN)
        self.assertEqual(vus["casse.txt"], filtres.LIEN)
        self.assertEqual([c for c, r in vus.items() if r is None], ["vrai.txt"])

    def test_dossier_choisi_sensible_refuse(self):
        coffre = self.racine / ".ssh"
        ecrire(coffre / "notes.txt")
        elements = list(filtres.parcourir(reglages_pour(coffre)))
        self.assertEqual([(e.raison, e.est_dossier) for e in elements], [(filtres.SENSIBLE, True)])

    def test_dossiers_imbriques_lus_une_seule_fois(self):
        ecrire(self.racine / "a" / "b.txt")
        regl = reglages_pour(self.racine, self.racine / "a", self.racine)
        chemins = [e.chemin for e in filtres.parcourir(regl) if e.raison is None]
        self.assertEqual(len(chemins), 1)

    def test_dossier_introuvable_signale(self):
        ecrire(self.racine / "a.txt")
        resultat = filtres.apercu(reglages_pour(self.racine, self.racine / "nexiste_pas"))
        self.assertEqual(resultat["acceptes"]["nombre"], 1)
        self.assertEqual(len(resultat["introuvables"]), 1)

    def test_apercu_compte_par_raison_avec_exemples(self):
        for i in range(8):
            ecrire(self.racine / f"note{i}.txt", "x" * 10)
            ecrire(self.racine / f"photo{i}.jpg")
        ecrire(self.racine / ".env")
        ecrire(self.racine / "node_modules" / "x" / "a.txt")
        resultat = filtres.apercu(reglages_pour(self.racine), exemples=3)
        self.assertEqual(resultat["acceptes"]["nombre"], 8)
        self.assertEqual(resultat["acceptes"]["taille"], 80)
        self.assertEqual(resultat["acceptes"]["par_type"], {".txt": 8})
        self.assertEqual(len(resultat["acceptes"]["exemples"]), 3)
        par_raison = {g["raison"]: g for g in resultat["ecartes"]}
        self.assertEqual(par_raison[filtres.TYPE]["fichiers"], 8)
        self.assertEqual(len(par_raison[filtres.TYPE]["exemples"]), 3)
        self.assertEqual(par_raison[filtres.SENSIBLE]["fichiers"], 1)
        self.assertEqual(par_raison[filtres.TECHNIQUE]["dossiers"], 1)

    def test_arret_demande(self):
        for i in range(5):
            ecrire(self.racine / f"d{i}" / "a.txt")
        self.assertEqual(list(filtres.parcourir(reglages_pour(self.racine), arret=lambda: True)), [])


class TestReglages(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dossier = Path(self._tmp.name)

    def test_premier_lancement_jamais_tout_le_disque(self):
        regl = reglages.charger(self.dossier)
        maison = str(Path.home())
        for dossier in regl["dossiers"]:
            self.assertTrue(dossier.startswith(maison) and dossier != maison, dossier)
            self.assertIn(Path(dossier).name, ("Documents", "Desktop", "Bureau", "Downloads", "Téléchargements"))
        self.assertIn("*.kdbx", regl["motifs_sensibles"])

    def test_enregistrer_puis_relire(self):
        regl = reglages.reglages_par_defaut()
        regl["dossiers"] = ["/quelque/part"]
        regl["extensions"] = ["TXT", "*.Md", ".pdf", "txt"]
        reglages.enregistrer(regl, self.dossier)
        relu = reglages.charger(self.dossier)
        self.assertEqual(relu["dossiers"], ["/quelque/part"])
        self.assertEqual(relu["extensions"], [".txt", ".md", ".pdf"])

    def test_valeurs_farfelues_remplacees(self):
        propre = reglages.nettoyer({"dossiers": "C:\\", "taille_max_mo": -5, "inclure_caches": "oui", "extensions": [3, ""]})
        self.assertEqual(propre["dossiers"], [])
        self.assertEqual(propre["taille_max_mo"], reglages.TAILLE_MAX_MO)
        self.assertFalse(propre["inclure_caches"])
        self.assertEqual(propre["extensions"], [])
        self.assertEqual(propre["motifs_sensibles"], reglages.MOTIFS_SENSIBLES)

    def test_fichier_abime(self):
        (self.dossier / reglages.NOM_FICHIER).write_text("{pas du json", encoding="utf-8")
        self.assertEqual(reglages.charger(self.dossier)["dossiers"], [])

    def test_dossier_de_donnees_windows(self):
        ancien = (sys.platform, os.environ.get("LOCALAPPDATA"), os.environ.pop("FOUINE_DONNEES", None))
        try:
            sys.platform = "win32"
            os.environ["LOCALAPPDATA"] = r"C:\Users\moi\AppData\Local"
            self.assertEqual(str(reglages.dossier_donnees()).replace("/", "\\"), r"C:\Users\moi\AppData\Local\Fouine")
        finally:
            sys.platform = ancien[0]
            for cle, valeur in (("LOCALAPPDATA", ancien[1]), ("FOUINE_DONNEES", ancien[2])):
                if valeur is None:
                    os.environ.pop(cle, None)
                else:
                    os.environ[cle] = valeur


if __name__ == "__main__":
    unittest.main()
