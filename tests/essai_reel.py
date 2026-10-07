"""Essai réel, de bout en bout, avec les vrais modèles (à lancer à la main).

Il n'est pas lancé avec les tests : il télécharge les deux modèles (environ 220 Mo
et 315 Mo) dans le dossier de données donné, et prend plusieurs minutes.

    python tests/essai_reel.py DOSSIER_A_LIRE DOSSIER_DE_DONNEES [questions.tsv]

`questions.tsv` : une ligne par question, « question <tabulation> nom du fichier attendu ».
Le script indexe le dossier (documents et images), puis dit à quel rang arrive le
fichier attendu, dans le bloc Documents ou dans le bloc Images.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fouine import images, reglages as mod_reglages  # noqa: E402
from fouine.embedding import Embedding  # noqa: E402
from fouine.images import EmbeddingImages  # noqa: E402
from fouine.index import Index  # noqa: E402


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    a_lire, donnees = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    reglages = mod_reglages.reglages_par_defaut()
    reglages.update(dossiers=[str(a_lire)], lire_images=True)
    index = Index(donnees, Embedding(donnees / "modele"), EmbeddingImages(donnees / "modele-images"))

    debuts = {}

    def progression(**infos):
        if infos["etape"] not in debuts:
            debuts[infos["etape"]] = time.monotonic()
            print(f"  étape « {infos['etape']} »", flush=True)

    debut = time.monotonic()
    bilan = index.indexer(reglages, progression=progression)
    print(f"Indexation en {time.monotonic() - debut:.0f} s : {bilan}")
    statistiques = index.statistiques()
    print(f"Index : {statistiques}")
    for illisible in index.illisibles():
        print("  pas pu être lu :", illisible)

    if len(sys.argv) > 3:
        premiers = {"documents": [0, 0], "images": [0, 0]}
        for ligne in Path(sys.argv[3]).read_text(encoding="utf-8").splitlines():
            if not ligne.strip():
                continue
            question, attendu = ligne.split("\t")
            bloc = "images" if images.est_image(attendu) else "documents"
            debut = time.monotonic()
            trouves = index.rechercher_images(question) if bloc == "images" else index.rechercher(question)
            duree = time.monotonic() - debut
            noms = [r["nom"] for r in trouves]
            rang = noms.index(attendu) + 1 if attendu in noms else None
            premiers[bloc][0] += rang == 1
            premiers[bloc][1] += 1
            notes = f" notes {trouves[0]['score']:.2f} à {trouves[-1]['score']:.2f}" if bloc == "images" and trouves else ""
            print(f"  {bloc:9} rang {rang!s:4} {duree:5.2f} s{notes}  {question}  ->  {noms[0] if noms else '(rien)'}")
        for bloc, (bons, total) in premiers.items():
            if total:
                print(f"Bon fichier en tête, bloc {bloc} : {bons}/{total}")
    try:
        import resource

        print(f"Mémoire au plus haut : {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss >> 10} Mo")
    except ImportError:  # Windows
        pass
    index.fermer()
    return 0


if __name__ == "__main__":
    sys.exit(main())
