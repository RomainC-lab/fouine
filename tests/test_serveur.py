import http.client
import json
import os
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path

from fouine import reglages as mod_reglages
from fouine.index import Index
from fouine.serveur import DOSSIER_WEB, Application, Serveur
from tests.outils import FauxEmbedding, ecrire, reglages_pour


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(os.path.realpath(self._tmp.name))
        self.docs = base / "Documents"
        self.donnees = base / "donnees"
        ecrire(self.docs / "plombier.txt", "Facture du plombier, fuite sous l'évier.")
        ecrire(self.docs / "outil.py", "print('bonjour plombier')")
        ecrire(self.docs / ".env", "CLE=tressecret")
        ecrire(base / "dehors.txt", "fichier hors des dossiers choisis")
        self.dehors = base / "dehors.txt"
        self.index = Index(self.donnees, FauxEmbedding())
        self.ouvertures = []
        self.application = Application(self.index, self.donnees, ouvrir=lambda c, q: self.ouvertures.append((c, q)))
        self.serveur = Serveur(self.application)
        self.port = self.serveur.server_address[1]
        fil = threading.Thread(target=self.serveur.serve_forever, daemon=True)
        fil.start()
        self.addCleanup(self._arreter, fil)
        mod_reglages.enregistrer(reglages_pour(self.docs), self.donnees)

    def _arreter(self, fil):
        self.application.arreter()
        self.application.attendre(10)
        self.serveur.shutdown()
        self.serveur.server_close()
        fil.join(5)
        self.index.fermer()

    def demander(self, methode, chemin, corps=None, jeton=True, entetes=None, hote=None, brut=None):
        connexion = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        tous = {"Host": hote or f"127.0.0.1:{self.port}"}
        if jeton:
            tous["X-Fouine-Jeton"] = self.serveur.jeton if jeton is True else jeton
        donnees = brut
        if corps is not None:
            donnees = json.dumps(corps).encode()
            tous["Content-Type"] = "application/json"
        tous.update(entetes or {})
        try:
            connexion.request(methode, chemin, body=donnees, headers=tous)
            reponse = connexion.getresponse()
            contenu = reponse.read()
        finally:
            connexion.close()
        if reponse.getheader("Content-Type", "").startswith("application/json"):
            contenu = json.loads(contenu)
        return reponse, contenu

    def api(self, action, corps=None, **options):
        return self.demander("POST", "/api/" + action, corps if corps is not None else {}, **options)

    def indexer(self):
        reponse, _ = self.api("indexer")
        self.assertEqual(reponse.status, 200)
        for _ in range(200):
            _, etat = self.demander("GET", "/api/etat")
            if not etat["tache"]["en_cours"]:
                return etat
            time.sleep(0.05)
        self.fail("indexation trop longue")


class TestSecurite(Base):
    def test_ecoute_seulement_en_local(self):
        self.assertEqual(self.serveur.server_address[0], "127.0.0.1")
        self.assertTrue(self.serveur.adresse.startswith("http://127.0.0.1:"))
        self.assertGreaterEqual(len(self.serveur.jeton), 32)

    def test_page_servie_avec_protections(self):
        reponse, contenu = self.demander("GET", "/", jeton=False)
        self.assertEqual(reponse.status, 200)
        self.assertIn(b"<title>Fouine</title>", contenu)
        politique = reponse.getheader("Content-Security-Policy")
        self.assertIn("default-src 'none'", politique)
        self.assertIn("frame-ancestors 'none'", politique)
        self.assertNotIn("unsafe", politique)
        self.assertEqual(reponse.getheader("X-Content-Type-Options"), "nosniff")
        self.assertIsNone(reponse.getheader("Access-Control-Allow-Origin"))
        self.assertNotIn(self.serveur.jeton.encode(), contenu, "le jeton n'est jamais dans la page")

    def test_hote_etranger_refuse(self):
        for hote in ("evil.example", f"evil.example:{self.port}", "127.0.0.1", "127.0.0.1:1", f"192.168.1.10:{self.port}", f"127.0.0.1.evil.example:{self.port}"):
            reponse, _ = self.demander("GET", "/", jeton=False, hote=hote)
            self.assertEqual(reponse.status, 403, hote)
            reponse, _ = self.demander("GET", "/api/etat", hote=hote)
            self.assertEqual(reponse.status, 403, hote)

    def test_localhost_accepte(self):
        reponse, _ = self.demander("GET", "/api/etat", hote=f"localhost:{self.port}")
        self.assertEqual(reponse.status, 200)

    def test_origine_etrangere_refusee(self):
        for origine in ("https://evil.example", "null", f"http://evil.example:{self.port}", f"https://127.0.0.1:{self.port}"):
            reponse, _ = self.api("recherche", {"question": "plombier"}, entetes={"Origin": origine})
            self.assertEqual(reponse.status, 403, origine)
        reponse, _ = self.api("recherche", {"question": "x"}, entetes={"Origin": f"http://127.0.0.1:{self.port}"})
        self.assertEqual(reponse.status, 200)

    def test_demande_d_un_autre_site_refusee(self):
        for valeur in ("cross-site", "same-site"):
            reponse, _ = self.api("recherche", {"question": "x"}, entetes={"Sec-Fetch-Site": valeur})
            self.assertEqual(reponse.status, 403, valeur)
        reponse, _ = self.demander("GET", "/", jeton=False, entetes={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(reponse.status, 403)

    def test_jeton_obligatoire_pour_toute_action(self):
        actions = ["enregistrer", "dossiers", "apercu", "indexer", "arreter", "recherche", "illisibles", "ouvrir"]
        self.assertEqual(sorted(actions), sorted(Application.ACTIONS))
        for action in actions:
            for jeton in (False, "faux", self.serveur.jeton[:-1]):
                reponse, _ = self.api(action, jeton=jeton)
                self.assertEqual(reponse.status, 403, action)
        reponse, _ = self.demander("GET", "/api/etat", jeton=False)
        self.assertEqual(reponse.status, 403)
        self.assertFalse(self.application.tache["en_cours"])

    def test_formulaire_classique_refuse(self):
        # Un formulaire d'un autre site ne peut pas envoyer du JSON : tout autre format est refusé.
        for type_contenu in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data"):
            reponse, _ = self.demander(
                "POST", "/api/recherche", brut=b'{"question": "x"}', entetes={"Content-Type": type_contenu}
            )
            self.assertEqual(reponse.status, 415, type_contenu)

    def test_demandes_mal_formees(self):
        reponse, _ = self.demander("POST", "/api/recherche", brut=b"{pas du json", entetes={"Content-Type": "application/json"})
        self.assertEqual(reponse.status, 400)
        reponse, _ = self.demander("POST", "/api/recherche", brut=b"[1, 2]", entetes={"Content-Type": "application/json"})
        self.assertEqual(reponse.status, 400)
        reponse, _ = self.api("recherche", {"question": 12})
        self.assertEqual(reponse.status, 400)
        reponse, _ = self.demander(
            "POST", "/api/recherche", brut=b"x", entetes={"Content-Type": "application/json", "Content-Length": "99999999"}
        )
        self.assertEqual(reponse.status, 413)
        reponse, _ = self.api("inconnue")
        self.assertEqual(reponse.status, 404)

    def test_autres_methodes_et_chemins_refuses(self):
        for methode in ("PUT", "DELETE", "PATCH", "OPTIONS"):
            reponse, _ = self.demander(methode, "/api/etat")
            self.assertEqual(reponse.status, 405, methode)
        for chemin in ("/../reglages.py", "/web/app.js", "/app.js/../../serveur.py", "/%2e%2e/secret", "/index.html"):
            reponse, _ = self.demander("GET", chemin, jeton=False)
            self.assertEqual(reponse.status, 404, chemin)
        reponse, _ = self.demander("GET", "/app.js", jeton=False)
        self.assertEqual(reponse.status, 200)

    def test_interface_sans_ressource_internet(self):
        for nom in ("index.html", "app.js", "style.css"):
            texte = (DOSSIER_WEB / nom).read_text(encoding="utf-8")
            self.assertEqual(re.findall(r"(?:https?:)?//[\w.-]+\.\w+", texte), [], nom)
            self.assertNotIn("@import", texte)
        page = (DOSSIER_WEB / "index.html").read_text(encoding="utf-8")
        self.assertNotRegex(page, r"<script(?![^>]*\bsrc=)")
        self.assertNotRegex(page, r"\son\w+=|style=")
        self.assertNotIn("innerHTML", (DOSSIER_WEB / "app.js").read_text(encoding="utf-8"))


class TestActions(Base):
    def test_parcours_complet(self):
        _, apercu = self.api("apercu")
        self.assertEqual(apercu["acceptes"]["nombre"], 1)
        self.assertEqual({g["raison"] for g in apercu["ecartes"]}, {"Fichier ou dossier sensible", "Type de fichier non lu"})
        etat = self.indexer()
        self.assertEqual(etat["tache"]["bilan"]["nouveaux"], 1)
        self.assertEqual(etat["index"]["fichiers"], 1)
        _, reponse = self.api("recherche", {"question": "facture plombier"})
        self.assertEqual([r["nom"] for r in reponse["resultats"]], ["plombier.txt"])
        self.assertNotIn("tressecret", json.dumps(reponse))

    def test_ouvrir_seulement_ce_qui_est_dans_l_index(self):
        self.indexer()
        _, reponse = self.api("recherche", {"question": "plombier"})
        identifiant = reponse["resultats"][0]["id"]
        for quoi in ("fichier", "dossier"):
            reponse, _ = self.api("ouvrir", {"id": identifiant, "quoi": quoi})
            self.assertEqual(reponse.status, 200)
        attendu = str(self.docs / "plombier.txt")
        self.assertEqual(self.ouvertures, [(attendu, "fichier"), (attendu, "dossier")])
        refuses = [
            {"id": 99999, "quoi": "fichier"},
            {"id": str(self.dehors), "quoi": "fichier"},
            {"id": attendu, "quoi": "fichier"},
            {"chemin": str(self.dehors), "quoi": "fichier"},
            {"id": identifiant, "quoi": "executer"},
            {"id": identifiant, "quoi": "fichier; calc.exe"},
            {"id": f"{identifiant} OR 1=1", "quoi": "fichier"},
            {"quoi": "dossier"},
        ]
        for corps in refuses:
            reponse, _ = self.api("ouvrir", corps)
            self.assertIn(reponse.status, (400, 404), corps)
        self.assertEqual(len(self.ouvertures), 2, "aucune ouverture en plus")

    def test_fichier_disparu_pas_ouvert(self):
        self.indexer()
        _, reponse = self.api("recherche", {"question": "plombier"})
        os.remove(self.docs / "plombier.txt")
        reponse, _ = self.api("ouvrir", {"id": reponse["resultats"][0]["id"], "quoi": "fichier"})
        self.assertEqual(reponse.status, 404)
        self.assertEqual(self.ouvertures, [])

    def test_programme_jamais_lance(self):
        mod_reglages.enregistrer(reglages_pour(self.docs, extensions=[".py"]), self.donnees)
        self.indexer()
        _, reponse = self.api("recherche", {"question": "bonjour plombier"})
        resultat = reponse["resultats"][0]
        self.assertEqual(resultat["nom"], "outil.py")
        reponse, _ = self.api("ouvrir", {"id": resultat["id"], "quoi": "fichier"})
        self.assertEqual(reponse.status, 403)
        reponse, _ = self.api("ouvrir", {"id": resultat["id"], "quoi": "dossier"})
        self.assertEqual(reponse.status, 200)
        self.assertEqual(self.ouvertures, [(str(self.docs / "outil.py"), "dossier")])

    def test_reglages_enregistres_et_sensibles_proteges(self):
        nouveaux = reglages_pour(self.docs, extensions=[".md"], taille_max_mo=5, motifs_sensibles=[], chemins_sensibles=[])
        reponse, corps = self.api("enregistrer", {"reglages": nouveaux})
        self.assertEqual(reponse.status, 200)
        self.assertEqual(corps["reglages"]["extensions"], [".md"])
        relu = mod_reglages.charger(self.donnees)
        self.assertEqual(relu["taille_max_mo"], 5)
        self.assertEqual(relu["motifs_sensibles"], mod_reglages.MOTIFS_SENSIBLES, "non modifiable depuis la page")
        self.assertEqual(relu["chemins_sensibles"], mod_reglages.CHEMINS_SENSIBLES)
        reponse, corps = self.api("enregistrer", {"reglages": {"defaut": True}})
        self.assertEqual(corps["reglages"]["extensions"], mod_reglages.EXTENSIONS)
        self.assertEqual(corps["reglages"]["dossiers"], [str(self.docs)], "les dossiers choisis sont gardés")
        reponse, _ = self.api("enregistrer", {"reglages": "x"})
        self.assertEqual(reponse.status, 400)

    def test_indexer_sans_dossier_refuse(self):
        mod_reglages.enregistrer(reglages_pour(), self.donnees)
        reponse, corps = self.api("indexer")
        self.assertEqual(reponse.status, 400)
        self.assertIn("dossier", corps["erreur"])

    def test_choix_de_dossier(self):
        ecrire(self.docs / "Factures" / "a.txt")
        ecrire(self.docs / ".cache" / "a.txt")
        _, corps = self.api("dossiers", {"chemin": str(self.docs)})
        self.assertEqual(corps["chemin"], str(self.docs))
        self.assertEqual(corps["parent"], str(self.docs.parent))
        self.assertEqual([d["nom"] for d in corps["sous_dossiers"]], ["Factures"])
        _, corps = self.api("dossiers", {"chemin": None})
        self.assertEqual(corps["chemin"], os.path.abspath(os.path.expanduser("~")))
        reponse, _ = self.api("dossiers", {"chemin": str(self.docs / "absent")})
        self.assertEqual(reponse.status, 404)

    def test_erreur_d_indexation_montree(self):
        def casse(*a, **k):
            raise RuntimeError("disque plein")

        self.index.indexer = casse
        etat = self.indexer()
        self.assertIn("disque plein", etat["tache"]["erreur"])
        self.assertFalse(etat["tache"]["en_cours"])


if __name__ == "__main__":
    unittest.main()
