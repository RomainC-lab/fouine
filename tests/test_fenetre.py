"""Ce qui entoure la fenêtre et se vérifie sans écran : thème retenu, instance unique,
journal, options de la ligne de commande, repli sur le navigateur."""

import contextlib
import http.client
import io
import json
import logging
import os
import socket
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

from fouine import __main__ as lancement
from fouine import __version__, boites, fenetre, instance as mod_instance, journal as mod_journal
from fouine import reglages as mod_reglages
from fouine.index import Index
from fouine.serveur import DOSSIER_WEB, Application, Serveur
from tests.outils import FauxEmbedding, FauxEmbeddingImages


class AvecDossier(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.donnees = Path(os.path.realpath(self._tmp.name)) / "donnees"

    def verrou_libre(self) -> bool:
        essai = mod_instance.Instance(self.donnees)
        try:
            return essai.prendre()
        finally:
            essai.liberer()

    def serveur(self):
        index = Index(self.donnees, FauxEmbedding(), FauxEmbeddingImages())
        serveur = Serveur(Application(index, self.donnees, ouvrir=lambda c, q: None))
        fil = threading.Thread(target=serveur.serve_forever, daemon=True)
        fil.start()

        def arreter():
            serveur.shutdown()
            serveur.server_close()
            fil.join(5)
            index.fermer()

        self.addCleanup(arreter)
        return serveur

    @staticmethod
    def demander(serveur, methode, chemin, corps=None, entetes=None):
        port = serveur.server_address[1]
        connexion = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        tous = dict(entetes or {})
        donnees = None
        if corps is not None:
            donnees = json.dumps(corps).encode()
            tous["Content-Type"] = "application/json"
        try:
            connexion.request(methode, chemin, body=donnees, headers=tous)
            reponse = connexion.getresponse()
            contenu = reponse.read()
        finally:
            connexion.close()
        return reponse.status, contenu


class TestTheme(AvecDossier):
    def test_sans_choix_la_page_suit_le_pc(self):
        serveur = self.serveur()
        code, page = self.demander(serveur, "GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b'<html lang="fr">', page)
        self.assertNotIn(b"data-theme", page)

    def test_theme_retenu_d_un_lancement_a_l_autre(self):
        premier = self.serveur()
        jeton = {"X-Fouine-Jeton": premier.jeton}
        code, _ = self.demander(premier, "POST", "/api/theme", {"theme": "dark"}, jeton)
        self.assertEqual(code, 200)
        self.assertEqual(json.loads((self.donnees / "interface.json").read_text(encoding="utf-8")), {"theme": "dark"})
        # Un autre lancement : autre port, autre jeton, même dossier de données.
        second = self.serveur()
        self.assertNotEqual(second.server_address[1], premier.server_address[1])
        _, page = self.demander(second, "GET", "/")
        self.assertIn(b'<html lang="fr" data-theme="dark">', page)
        self.demander(second, "POST", "/api/theme", {"theme": "light"}, {"X-Fouine-Jeton": second.jeton})
        _, page = self.demander(second, "GET", "/")
        self.assertIn(b'<html lang="fr" data-theme="light">', page)

    def test_theme_inconnu_ou_sans_jeton_refuse(self):
        serveur = self.serveur()
        jeton = {"X-Fouine-Jeton": serveur.jeton}
        for choix in ("rose", "", None, 3, 'dark"><script>'):
            code, _ = self.demander(serveur, "POST", "/api/theme", {"theme": choix}, jeton)
            self.assertEqual(code, 400, choix)
        code, _ = self.demander(serveur, "POST", "/api/theme", {"theme": "dark"})
        self.assertEqual(code, 403)
        self.assertFalse((self.donnees / "interface.json").exists())

    def test_fichier_abime_ou_trafique_sans_effet(self):
        self.donnees.mkdir(parents=True)
        for contenu in ("{pas du json", '["dark"]', '{"theme": "dark\\"><script>alert(1)</script>"}', '{"theme": 1}'):
            (self.donnees / "interface.json").write_text(contenu, encoding="utf-8")
            self.assertIsNone(mod_reglages.charger_theme(self.donnees), contenu)
        _, page = self.demander(self.serveur(), "GET", "/")
        self.assertNotIn(b"data-theme", page)
        self.assertNotIn(b"alert(1)", page)

    def test_le_theme_ne_touche_pas_aux_reglages(self):
        serveur = self.serveur()
        avant = mod_reglages.enregistrer(mod_reglages.reglages_par_defaut(), self.donnees)
        self.demander(serveur, "POST", "/api/theme", {"theme": "dark"}, {"X-Fouine-Jeton": serveur.jeton})
        self.assertEqual(mod_reglages.charger(self.donnees), avant)

    def test_la_page_ne_compte_plus_sur_la_memoire_du_navigateur(self):
        script = (DOSSIER_WEB / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("localStorage", script)
        self.assertIn('appeler("theme"', script)
        self.assertIn(b'<html lang="fr">', (DOSSIER_WEB / "index.html").read_bytes())


class TestInstanceUnique(AvecDossier):
    def test_un_seul_fouine_par_dossier(self):
        premiere, seconde = mod_instance.Instance(self.donnees), mod_instance.Instance(self.donnees)
        self.addCleanup(premiere.liberer)
        self.addCleanup(seconde.liberer)
        self.assertTrue(premiere.prendre())
        self.assertFalse(seconde.prendre())
        premiere.liberer()
        self.assertTrue(seconde.prendre(), "le verrou est rendu à l'arrêt")

    def test_deux_dossiers_deux_instances(self):
        premiere = mod_instance.Instance(self.donnees)
        autre = mod_instance.Instance(self.donnees.parent / "autre")
        self.addCleanup(premiere.liberer)
        self.addCleanup(autre.liberer)
        self.assertTrue(premiere.prendre())
        self.assertTrue(autre.prendre())

    def test_reveil_du_premier_par_le_second(self):
        serveur = self.serveur()
        premiere = mod_instance.Instance(self.donnees)
        self.addCleanup(premiere.liberer)
        self.assertTrue(premiere.prendre())
        appels = []
        serveur.cle_instance = premiere.cle
        serveur.premier_plan = lambda: appels.append("devant")
        premiere.annoncer(serveur.server_address[1])
        annonce = (self.donnees / "instance.json").read_text(encoding="utf-8")
        self.assertNotIn(serveur.jeton, annonce, "le jeton de la page n'est jamais écrit sur le disque")
        self.assertTrue(mod_instance.reveiller(self.donnees))
        self.assertEqual(appels, ["devant"])
        self.assertEqual(serveur.reveils, 1)
        premiere.liberer()
        self.assertFalse((self.donnees / "instance.json").exists())
        self.assertFalse(mod_instance.reveiller(self.donnees))

    def test_reveil_refuse_sans_la_bonne_cle(self):
        serveur = self.serveur()
        appels = []
        serveur.premier_plan = lambda: appels.append("devant")
        port = serveur.server_address[1]
        # Tant qu'aucune clé n'est posée, personne ne peut demander quoi que ce soit.
        code, _ = self.demander(serveur, "POST", "/api/premier-plan", {}, {"X-Fouine-Instance": ""})
        self.assertEqual(code, 403)
        serveur.cle_instance = "la-bonne-cle"
        for entetes in (
            {},
            {"X-Fouine-Instance": "une-autre"},
            {"X-Fouine-Jeton": serveur.jeton},  # le jeton de la page ne sert pas à ça
            {"X-Fouine-Instance": "la-bonne-cle", "Origin": "https://evil.example"},
            {"X-Fouine-Instance": "la-bonne-cle", "Sec-Fetch-Site": "cross-site"},
            {"X-Fouine-Instance": "la-bonne-cle", "Host": f"evil.example:{port}"},
        ):
            code, _ = self.demander(serveur, "POST", "/api/premier-plan", {}, entetes)
            self.assertEqual(code, 403, entetes)
        self.assertEqual(appels, [])
        # La clé d'instance n'ouvre rien d'autre.
        code, _ = self.demander(serveur, "GET", "/api/etat", None, {"X-Fouine-Instance": "la-bonne-cle"})
        self.assertEqual(code, 403)
        code, _ = self.demander(serveur, "POST", "/api/recherche", {"question": "x"}, {"X-Fouine-Instance": "la-bonne-cle"})
        self.assertEqual(code, 403)
        code, _ = self.demander(serveur, "POST", "/api/premier-plan", {}, {"X-Fouine-Instance": "la-bonne-cle"})
        self.assertEqual(code, 200)
        self.assertEqual(appels, ["devant"])

    def test_annonce_illisible_ou_fouine_disparu(self):
        self.assertFalse(mod_instance.reveiller(self.donnees))
        self.donnees.mkdir(parents=True)
        for contenu in ("", "{", '{"port": "abc", "cle": "x", "pid": 1}', '{"port": 80}'):
            (self.donnees / "instance.json").write_text(contenu, encoding="utf-8")
            self.assertFalse(mod_instance.reveiller(self.donnees), contenu)
        with socket.socket() as prise:  # un port où plus personne n'écoute
            prise.bind(("127.0.0.1", 0))
            port = prise.getsockname()[1]
        (self.donnees / "instance.json").write_text(json.dumps({"port": port, "cle": "x", "pid": 1}), encoding="utf-8")
        self.assertFalse(mod_instance.reveiller(self.donnees, delai=2))


class TestJournal(AvecDossier):
    def setUp(self):
        super().setUp()
        self.addCleanup(mod_journal.fermer)
        for nom in ("excepthook",):
            ancien = getattr(sys, nom)
            self.addCleanup(setattr, sys, nom, ancien)
        self.addCleanup(setattr, threading, "excepthook", threading.excepthook)

    def test_messages_ecrits_dans_le_dossier_de_donnees(self):
        fichier = mod_journal.installer(self.donnees)
        self.assertEqual(fichier, self.donnees / "fouine.log")
        mod_journal.journal.info("Fouine est lancé, avec des accents : é à ç")
        mod_journal.fermer()
        self.assertIn("Fouine est lancé, avec des accents : é à ç", fichier.read_text(encoding="utf-8"))

    def test_taille_bornee(self):
        fichier = mod_journal.installer(self.donnees)
        ligne = "x" * 1000
        for _ in range(3 * mod_journal.TAILLE_MAX // 1000):
            mod_journal.journal.info(ligne)
        mod_journal.fermer()
        self.assertLessEqual(fichier.stat().st_size, mod_journal.TAILLE_MAX)
        self.assertEqual(sorted(p.name for p in self.donnees.iterdir()), ["fouine.log", "fouine.log.1"])
        self.assertLessEqual((self.donnees / "fouine.log.1").stat().st_size, mod_journal.TAILLE_MAX)

    def test_sans_console_tout_va_au_journal(self):
        with mock.patch.object(sys, "stdout", None), mock.patch.object(sys, "stderr", None), \
                mock.patch.dict(os.environ), mock.patch.object(logging, "raiseExceptions", True):
            fichier = mod_journal.installer(self.donnees)
            print("message d'une bibliothèque")
            sys.stderr.write("barre 10%\rbarre 100%\nfin")
            sys.stderr.write(" de ligne\n")
            self.assertEqual(os.environ.get("HF_HUB_DISABLE_PROGRESS_BARS"), "1")
            sys.excepthook(ValueError, ValueError("erreur perdue"), None)
        mod_journal.fermer()
        contenu = fichier.read_text(encoding="utf-8")
        for attendu in ("INFO message d'une bibliothèque", "WARNING barre 100%", "WARNING fin de ligne",
                        "ERROR Erreur inattendue", "ValueError: erreur perdue"):
            self.assertIn(attendu, contenu)

    def test_connexion_coupee_par_la_fenetre_sans_bruit(self):
        fichier = mod_journal.installer(self.donnees)
        serveur = self.serveur()
        with contextlib.redirect_stderr(io.StringIO()) as erreurs:
            for erreur in (ConnectionResetError("coupée"), BrokenPipeError("coupée"), ValueError("autre chose")):
                try:
                    raise erreur
                except Exception:
                    serveur.handle_error(None, ("127.0.0.1", 1))
        mod_journal.fermer()
        self.assertEqual(erreurs.getvalue(), "")
        contenu = fichier.read_text(encoding="utf-8")
        self.assertEqual(contenu.count("Demande interrompue"), 1)
        self.assertIn("Demande interrompue (ValueError).", contenu)
        self.assertNotIn("Traceback", contenu)

    def test_dossier_impossible_fouine_marche_quand_meme(self):
        self.donnees.parent.mkdir(parents=True, exist_ok=True)
        self.donnees.write_text("un fichier à la place du dossier", encoding="utf-8")
        self.assertIsNone(mod_journal.installer(self.donnees))
        mod_journal.journal.info("perdu, mais sans erreur")


class FauxEvenement(list):
    def __iadd__(self, fonction):
        self.append(fonction)
        return self


class FausseFenetre:
    """Ce que `fenetre.ouvrir` attend de pywebview, sans écran."""

    def __init__(self, titre, adresse, **options):
        self.titre, self.adresse, self.options = titre, adresse, options
        self.confirm_close = False
        self.detruite = threading.Event()
        self.events = types.SimpleNamespace(closing=FauxEvenement(), closed=threading.Event())
        self.events.closed.is_set = self.detruite.is_set

    def destroy(self):
        self.detruite.set()

    def demander_fermeture(self):
        """Comme un clic sur la croix : rend True si pywebview poserait la question."""
        for fonction in self.events.closing:
            fonction()
        return self.confirm_close


def faux_webview(au_demarrage):
    module = types.ModuleType("webview")
    module.settings = {"ALLOW_DOWNLOADS": True, "ALLOW_FILE_URLS": True, "OPEN_EXTERNAL_LINKS_IN_BROWSER": False}
    module.fenetres = []
    module.demarrages = []

    def create_window(titre, adresse, **options):
        module.fenetres.append(FausseFenetre(titre, adresse, **options))
        return module.fenetres[-1]

    def start(fonction=None, **options):
        module.demarrages.append(options)
        fil = threading.Thread(target=fonction, daemon=True)
        fil.start()
        au_demarrage(module.fenetres[-1])
        fil.join(10)

    module.create_window, module.start = create_window, start
    return module


class TestFenetre(AvecDossier):
    def ouvrir(self, serveur, au_demarrage, **options):
        module = faux_webview(au_demarrage)
        with mock.patch.dict(sys.modules, {"webview": module}), mock.patch.object(fenetre, "verifier"):
            try:
                fenetre.ouvrir(serveur, **options)
            finally:
                self.module = module
        return module

    def test_fenetre_sur_la_page_locale_sans_rien_offrir_a_la_page(self):
        serveur = self.serveur()
        mod_reglages.enregistrer_theme("dark", self.donnees)

        def utilisateur(fausse):
            serveur.page_vivante.set()  # la page s'est affichée
            fausse.destroy()  # puis l'utilisateur ferme

        module = self.ouvrir(serveur, utilisateur)
        fausse = module.fenetres[0]
        self.assertEqual(fausse.titre, "Fouine")
        self.assertEqual(fausse.adresse, serveur.adresse_complete)
        self.assertTrue(fausse.adresse.startswith("http://127.0.0.1:"))
        self.assertNotIn("js_api", fausse.options, "aucune fonction Python n'est offerte à la page")
        self.assertEqual(fausse.options["min_size"], fenetre.TAILLE_MIN)
        self.assertEqual(fausse.options["background_color"], "#0e1613")
        self.assertEqual(module.settings, {"ALLOW_DOWNLOADS": False, "ALLOW_FILE_URLS": False,
                                           "OPEN_EXTERNAL_LINKS_IN_BROWSER": True})
        self.assertNotIn("debug", module.demarrages[0])
        self.assertNotIn("http_server", module.demarrages[0])
        self.assertIn("indexation", module.demarrages[0]["localization"]["global.quitConfirmation"])
        self.assertIsNone(serveur.premier_plan, "plus de fenêtre à ramener devant une fois fermée")

    def test_question_avant_de_fermer_seulement_pendant_une_indexation(self):
        serveur = self.serveur()
        reponses = []

        def utilisateur(fausse):
            serveur.page_vivante.set()
            reponses.append(fausse.demander_fermeture())
            serveur.application.tache["en_cours"] = True
            reponses.append(fausse.demander_fermeture())
            serveur.application.tache["en_cours"] = False
            reponses.append(fausse.demander_fermeture())
            fausse.destroy()

        self.ouvrir(serveur, utilisateur)
        self.assertEqual(reponses, [False, True, False])

    def test_page_jamais_affichee_la_fenetre_est_refermee(self):
        serveur = self.serveur()
        with mock.patch.object(fenetre, "DELAI_PAGE", 0.3):
            with self.assertRaises(fenetre.Indisponible) as contexte:
                self.ouvrir(serveur, lambda fausse: fausse.detruite.wait(10))
        self.assertIn("ne s'est pas affichée", str(contexte.exception))
        self.assertTrue(self.module.fenetres[0].detruite.is_set())

    def test_erreur_de_pywebview_traduite(self):
        serveur = self.serveur()

        def casse(fausse):
            raise RuntimeError("moteur absent")

        with self.assertRaises(fenetre.Indisponible) as contexte:
            self.ouvrir(serveur, casse)
        self.assertIn("moteur absent", str(contexte.exception))

    def test_sans_pywebview_la_fenetre_est_dite_indisponible(self):
        with mock.patch.dict(sys.modules, {"webview": None}):
            with self.assertRaises(fenetre.Indisponible) as contexte:
                fenetre.verifier()
        self.assertIn("pywebview", str(contexte.exception))

    @unittest.skipIf(sys.platform in ("win32", "darwin"), "question propre à Linux")
    def test_sans_ecran_la_fenetre_est_dite_indisponible(self):
        vide = {cle: valeur for cle, valeur in os.environ.items() if cle not in ("DISPLAY", "WAYLAND_DISPLAY")}
        with mock.patch.dict(sys.modules, {"webview": types.ModuleType("webview")}), \
                mock.patch.dict(os.environ, vide, clear=True):
            with self.assertRaises(fenetre.Indisponible):
                fenetre.verifier()


class TestLancement(AvecDossier):
    """`main` en entier, avec la fenêtre, le navigateur et les boîtes de message remplacés."""

    def setUp(self):
        super().setUp()
        self.messages = []
        self.navigateur = []
        self.fenetres = []
        self.attentes = []
        self.addCleanup(setattr, sys, "excepthook", sys.excepthook)
        self.addCleanup(setattr, threading, "excepthook", threading.excepthook)
        for cible in (
            mock.patch.dict(os.environ),
            mock.patch.object(boites, "informer", lambda texte: self.messages.append(("info", texte))),
            mock.patch.object(boites, "erreur", lambda texte: self.messages.append(("erreur", texte))),
            mock.patch.object(lancement.webbrowser, "open", lambda adresse: self.navigateur.append(adresse)),
            mock.patch.object(lancement, "_attendre_sans_fenetre", lambda serveur, _: self.attentes.append(serveur)),
        ):
            cible.start()
            self.addCleanup(cible.stop)

    def lancer(self, *arguments, fenetre_ouvre=None):
        def ouvrir(serveur, essai=None):
            self.fenetres.append(serveur.adresse_complete)
            if fenetre_ouvre is not None:
                fenetre_ouvre(serveur)

        with mock.patch.object(fenetre, "ouvrir", ouvrir), contextlib.redirect_stdout(io.StringIO()) as sortie:
            code = lancement.main(["--donnees", str(self.donnees), *arguments])
        self.sortie = sortie.getvalue()
        return code

    def test_par_defaut_une_fenetre_et_pas_de_navigateur(self):
        self.assertEqual(self.lancer(), 0)
        self.assertEqual(len(self.fenetres), 1)
        self.assertEqual(self.navigateur, [])
        self.assertEqual(self.messages, [])
        journal = (self.donnees / "fouine.log").read_text(encoding="utf-8")
        self.assertIn(f"Fouine {__version__} est lancé", journal)
        self.assertIn("Fouine est arrêté.", journal)
        self.assertNotIn("#", journal, "le jeton n'est pas écrit dans le journal")
        self.assertFalse((self.donnees / "instance.json").exists(), "plus d'annonce une fois arrêté")
        self.assertTrue(self.verrou_libre(), "le verrou est rendu")

    def test_option_navigateur(self):
        self.assertEqual(self.lancer("--navigateur"), 0)
        self.assertEqual(self.fenetres, [])
        self.assertEqual(len(self.navigateur), 1)
        self.assertRegex(self.navigateur[0], r"^http://127\.0\.0\.1:\d+/#.{40,}$")
        self.assertEqual(len(self.attentes), 1)

    def test_fenetre_impossible_repli_sur_le_navigateur_avec_un_message(self):
        def impossible(serveur):
            raise fenetre.Indisponible("le composant WebView2 de Microsoft Edge n'est pas installé sur ce PC")

        self.assertEqual(self.lancer(fenetre_ouvre=impossible), 0)
        self.assertEqual(len(self.navigateur), 1)
        self.assertEqual(len(self.messages), 1)
        genre, texte = self.messages[0]
        self.assertEqual(genre, "info")
        self.assertIn("WebView2", texte)
        self.assertIn("navigateur", texte)

    def test_sans_navigateur_ni_fenetre(self):
        self.assertEqual(self.lancer("--sans-navigateur"), 0)
        self.assertEqual((self.fenetres, self.navigateur), ([], []))
        self.assertEqual(len(self.attentes), 1)

    def test_second_lancement_reveille_le_premier_et_s_arrete(self):
        codes = []

        def pendant_que_le_premier_tourne(serveur):
            reveils = []
            serveur.premier_plan = lambda: reveils.append(1)
            fils = threading.Thread(target=lambda: codes.append(lancement.main(["--donnees", str(self.donnees)])))
            fils.start()
            fils.join(30)
            codes.append(len(reveils))

        self.assertEqual(self.lancer(fenetre_ouvre=pendant_que_le_premier_tourne), 0)
        self.assertEqual(codes, [0, 1], "le second s'arrête sans erreur après un réveil du premier")
        self.assertEqual(len(self.fenetres), 1, "le second n'ouvre pas de fenêtre")
        self.assertEqual(self.messages, [])

    def test_fouine_deja_lance_mais_muet_on_le_dit(self):
        autre = mod_instance.Instance(self.donnees)
        self.addCleanup(autre.liberer)
        self.assertTrue(autre.prendre())
        self.assertEqual(self.lancer(), 0)
        self.assertEqual(self.fenetres, [])
        self.assertEqual([genre for genre, _ in self.messages], ["info"])
        self.assertIn("déjà lancé", self.messages[0][1])

    def test_port_pris_message_clair(self):
        with socket.socket() as prise:
            prise.bind(("127.0.0.1", 0))
            prise.listen()
            port = prise.getsockname()[1]
            self.assertEqual(self.lancer("--port", str(port)), 1)
        self.assertEqual(self.fenetres, [])
        self.assertEqual([genre for genre, _ in self.messages], ["erreur"])
        self.assertIn(f"le port {port} est déjà pris", self.messages[0][1])
        self.assertIn("fouine.log", self.messages[0][1])
        self.assertTrue(self.verrou_libre(), "le verrou est rendu après l'échec")

    def test_erreur_imprevue_dite_et_ecrite(self):
        def casse(serveur):
            raise RuntimeError("panne imprévue")

        self.assertEqual(self.lancer(fenetre_ouvre=casse), 1)
        self.assertEqual([genre for genre, _ in self.messages], ["erreur"])
        self.assertIn("panne imprévue", self.messages[0][1])
        self.assertIn("panne imprévue", (self.donnees / "fouine.log").read_text(encoding="utf-8"))

    def test_essai_de_fenetre_rate_si_elle_ne_s_ouvre_pas(self):
        def impossible(serveur):
            raise fenetre.Indisponible("pas d'écran graphique")

        self.assertEqual(self.lancer("--essai-fenetre", fenetre_ouvre=impossible), 1)
        self.assertIn("RATÉ", self.sortie)
        self.assertEqual(self.navigateur, [], "pas de repli pendant l'essai")

    def test_version_et_aide(self):
        for arguments, attendu in ((["--version"], f"Fouine {__version__}"), (["--help"], "--navigateur")):
            with contextlib.redirect_stdout(io.StringIO()) as sortie, self.assertRaises(SystemExit) as fin:
                lancement.main(arguments)
            self.assertEqual(fin.exception.code, 0)
            self.assertIn(attendu, sortie.getvalue())
        self.assertNotIn("essai-fenetre", sortie.getvalue(), "option réservée à la fabrication")
        self.assertEqual(self.fenetres, [])


if __name__ == "__main__":
    unittest.main()
