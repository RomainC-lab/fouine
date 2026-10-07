# Recette PyInstaller de Fouine : un dossier « Fouine » avec Fouine.exe dedans.
#
#   pip install -r emballage/requirements-exe.txt
#   pyinstaller --noconfirm --clean emballage/Fouine.spec
#
# Les modèles ne sont pas dans le paquet : Fouine les télécharge au premier besoin.

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

racine = Path(SPECPATH).parent

donnees = [(str(racine / "fouine" / "web"), "fouine/web")]
# Bibliothèques qui lisent leurs propres fichiers ou leur numéro de version une fois installées.
for paquet in ("fastembed", "huggingface_hub", "onnxruntime", "tokenizers", "tqdm", "requests", "filelock", "numpy"):
    donnees += copy_metadata(paquet)
donnees += collect_data_files("fastembed")

analyse = Analysis(
    [str(racine / "emballage" / "fouine_exe.py")],
    pathex=[str(racine)],
    datas=donnees,
    hiddenimports=["fouine.autotest", "fouine.factice", "PIL.JpegImagePlugin", "PIL.PngImagePlugin",
                   "PIL.WebPImagePlugin", "PIL.GifImagePlugin", "PIL.BmpImagePlugin", "PIL.TiffImagePlugin"],
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "torch", "tensorflow"],
    noarchive=False,
)
# Bibliothèques Microsoft (Visual C++) dont Python et ONNX Runtime ont besoin : elles ne sont
# pas sur tous les PC. On les met à côté de Fouine.exe, pour qu'il ne dépende de rien d'autre.
if sys.platform == "win32":
    deja = {Path(binaire[0]).name.lower() for binaire in analyse.binaries}
    endroits = [Path(sys.base_prefix), Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"]
    for nom in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
                "msvcp140_atomic_wait.dll", "msvcp140_codecvt_ids.dll", "concrt140.dll"):
        if nom in deja:
            continue
        for endroit in endroits:
            if (endroit / nom).is_file():
                analyse.binaries.append((nom, str(endroit / nom), "BINARY"))
                break

pyz = PYZ(analyse.pure)
exe = EXE(
    pyz,
    analyse.scripts,
    [],
    exclude_binaries=True,
    name="Fouine",
    icon=str(racine / "emballage" / "fouine.ico"),
    console=True,  # la fenêtre noire reste visible : la fermer arrête Fouine
    upx=False,  # pas de compression : elle déclenche de fausses alertes d'antivirus
)
COLLECT(exe, analyse.binaries, analyse.datas, name="Fouine", upx=False)
