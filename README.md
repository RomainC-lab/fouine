# Fouine

Fouine retrouve vos fichiers **par leur contenu et par leur sens**, sur votre PC.
Vous tapez « combien m'a coûté la réparation de la fuite d'eau » et Fouine vous
montre la facture du plombier, même si aucun de ces mots n'est dans le nom du fichier.

**Tout se passe sur votre PC.** Vos fichiers, leur texte et vos recherches ne
sont envoyés nulle part.

![Une recherche dans Fouine](docs/capture-recherche.png)

> Petite version (0.2). Elle fait peu de choses, volontairement. La 0.2 refait toute l'interface : thème clair et thème sombre (bouton en haut à droite), mêmes fonctions.

## Ce qui reste sur votre PC, et la seule connexion à Internet

- Fouine lit vos fichiers et calcule leur « empreinte de sens » (embedding) **sur votre PC**, avec un petit modèle de langue.
- L'index est un simple fichier rangé sur votre PC (sous Windows : `%LOCALAPPDATA%\Fouine`).
- L'interface s'affiche dans votre navigateur, mais la page vient de votre PC (adresse `127.0.0.1`). Elle ne charge rien depuis Internet et n'est pas visible depuis un autre appareil.
- **Fouine se connecte à Internet dans un seul cas** : la première fois, pour télécharger le modèle de langue (environ 220 Mo, depuis le site Hugging Face). Ensuite il marche sans connexion.
- L'installation (`installer.bat`) télécharge aussi, une fois, les bibliothèques Python nécessaires.

## Installation sous Windows, pas à pas

1. **Installer Python** (gratuit), si ce n'est pas déjà fait : allez sur <https://www.python.org/downloads/>, téléchargez Python (version 3.10 ou plus récente), lancez l'installation et **cochez la case « Add python.exe to PATH »** avant de cliquer sur « Install Now ».
2. **Télécharger Fouine** : sur cette page, bouton vert « Code », puis « Download ZIP ». Décompressez le dossier où vous voulez (par exemple dans `Documents`).
3. Dans le dossier décompressé, **double-cliquez sur `installer.bat`**. Une fenêtre noire travaille quelques minutes. À faire une seule fois.
4. **Double-cliquez sur `lancer.bat`**. Une fenêtre noire reste ouverte (c'est Fouine qui tourne) et votre navigateur ouvre la page de Fouine.

Pour arrêter Fouine, fermez la fenêtre noire.

Sous Linux ou macOS : `./installer.sh`, puis `./lancer.sh`.

## Utilisation

1. Onglet **« Dossiers et filtres »** : choisissez les dossiers que Fouine a le droit de lire. Au premier lancement il propose Documents, Bureau et Téléchargements. Il ne lit jamais tout le disque, sauf si vous le choisissez vous-même.
2. Cliquez sur **« Voir ce qui serait lu »** : Fouine compte les fichiers qui seraient lus et ceux qui seraient laissés de côté, raison par raison, avec des exemples. Rien n'est encore ouvert.
3. Cliquez sur **« Indexer maintenant »**. La première fois, c'est long (téléchargement du modèle, puis lecture de tous les fichiers). Vous pouvez arrêter et reprendre plus tard : ce qui est fait reste fait.
4. Onglet **« Chercher »** : décrivez ce que vous cherchez, avec vos mots. Chaque résultat montre un extrait, l'emplacement, la date, et deux boutons pour ouvrir le fichier ou son dossier.

Quand vos fichiers changent, relancez « Indexer maintenant » : seuls les fichiers nouveaux ou modifiés sont relus, et les fichiers supprimés sortent de l'index. Cette mise à jour n'est pas automatique.

![Les filtres et l'aperçu avant indexation](docs/capture-filtres.png)

Le thème sombre suit le réglage de votre PC ; le bouton en haut à droite permet d'en changer.

![Une recherche avec le thème sombre](docs/capture-sombre.png)

## Ce qui est laissé de côté par défaut

| Quoi | Détail |
| --- | --- |
| **Fichiers sensibles** (jamais lus) | `.env`, `*.pem`, `*.key`, `id_rsa*`, `*.kdbx`, `*.pfx`, `*.p12`, portefeuilles (`wallet`), dossiers `.ssh`, `.gnupg`, profils de navigateur (Chrome, Edge, Firefox, Brave…), et tout fichier ou dossier dont le nom contient « password », « mot de passe », « mdp », « secret », « identifiants ». |
| **Dossiers du système** | `Windows`, `Program Files`, `ProgramData`, `AppData`, `$Recycle.Bin`… (et `/proc`, `/sys`, `/etc`… sous Linux). |
| **Dossiers techniques** | `.git`, `node_modules`, `venv`, `__pycache__`, caches. |
| **Fichiers et dossiers cachés** | Ceux dont le nom commence par un point, ou marqués « cachés » sous Windows. |
| **Tout ce qui n'est pas un document** | Seuls ces types sont lus : `.txt` `.md` `.rst` `.csv` `.tsv` `.html` `.htm` `.pdf` `.docx` `.pptx` `.xlsx` `.odt` `.odp` `.ods`. Photos, vidéos, musique, archives, programmes : jamais ouverts. |
| **Fichiers trop gros** | Plus de 20 Mo. |
| **Raccourcis (liens symboliques)** | Jamais suivis : Fouine ne sort pas des dossiers choisis. |

Un dossier laissé de côté n'est pas ouvert du tout.

Ces réglages se changent dans la page (types de fichiers, taille, noms de dossiers, fichiers cachés) ou dans le fichier `reglages.json` du dossier de données, lisible avec le Bloc-notes. La liste des fichiers sensibles ne se change que dans ce fichier, pour éviter de la vider par erreur.

## Limites connues

- **PDF scannés et images** : Fouine ne lit pas le texte d'une image (pas de reconnaissance de caractères). Un PDF scanné reste trouvable par son nom seulement.
- **Tableurs** : seul le texte des cellules est lu, pas les nombres ; la recherche par le sens y marche moins bien.
- **Anciens formats** `.doc`, `.xls`, `.ppt` : non lus.
- Les filtres sur les noms sont volontairement prudents : un fichier appelé `secretariat.txt` est écarté parce que son nom contient « secret ». L'aperçu le montre.
- Un texte très long est coupé après environ 400 pages.
- Les résultats peuvent contenir, en fin de liste, des fichiers sans grand rapport : le modèle est petit.
- Pensé pour quelques milliers à quelques dizaines de milliers de documents. Au-delà, la recherche ralentit et prend plus de mémoire.
- L'index contient le texte de vos documents, en clair, sur votre PC : il est aussi privé qu'eux.
- Écrit pour Windows, Linux et macOS, mais **testé pour l'instant sous Linux seulement**.

## Pour tout effacer

Supprimez le dossier de Fouine, et le dossier de données : `%LOCALAPPDATA%\Fouine` sous Windows (tapez ce chemin dans la barre d'adresse de l'Explorateur), `~/.local/share/fouine` sous Linux, `~/Library/Application Support/Fouine` sous macOS. Vos fichiers ne sont jamais modifiés par Fouine.

## Pour les curieux

- Python, peu de dépendances : [fastembed](https://github.com/qdrant/fastembed) (calcul des embeddings avec ONNX, sans PyTorch), `numpy`, `pypdf`. Les documents Office et LibreOffice sont lus avec la bibliothèque standard.
- Modèle : `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (multilingue, 384 dimensions).
- Index : un fichier SQLite ; le texte est découpé en morceaux qui se chevauchent ; la recherche mélange la ressemblance de sens (cosinus) et la recherche par mots (FTS5).
- Serveur local : écoute sur `127.0.0.1` uniquement, port libre choisi au lancement, vérifie les en-têtes `Host` et `Origin`, demande un jeton secret tiré au hasard à chaque lancement ; « ouvrir le fichier » n'accepte qu'un fichier présent dans l'index.
- Tests : `python -m unittest discover -s tests -t .`

## Licence

MIT — voir [LICENSE](LICENSE).
