"""Fabrique l'icône de Fouine (`emballage/fouine.ico` et `fouine/icone.png`) à partir de l'emblème.

À relancer seulement si le dessin change ; le résultat est rangé dans le dépôt. Il faut
Pillow, et PyGObject avec librsvg pour dessiner le SVG (sous Linux : paquets `python3-gi`
et `gir1.2-rsvg-2.0`) :

    python3 emballage/icone.py
"""

from __future__ import annotations

import io
from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gio, GLib  # noqa: E402
from PIL import Image  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent
TAILLES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

_OREILLES = (
    '<path fill="#8a705e" d="M8.5 25C5.5 13 9.5 4.5 17 4.5c6.5 0 10.5 6 10.5 14z"/>'
    '<path fill="#8a705e" d="M55.5 25C58.5 13 54.5 4.5 47 4.5c-6.5 0-10.5 6-10.5 14z"/>'
    '<path fill="#d3a996" d="M12.5 21C11 14 13.5 9.5 17 9.5c3.5 0 5.5 4 5.5 9z"/>'
    '<path fill="#d3a996" d="M51.5 21C53 14 50.5 9.5 47 9.5c-3.5 0-5.5 4-5.5 9z"/>'
)
_TETE = (
    '<path fill="#8a705e" d="M32 11c12 0 24 6 24 18 0 9-9.5 14.5-14.5 21-3 4-6 6-9.5 6s-6.5-2-9.5-6'
    'C17.5 43.5 8 38 8 29c0-12 12-18 24-18z"/>'
    '<path fill="#f6efe2" d="M32 35c4 0 8 3.5 8.5 8.5C40 49 36 56 32 56s-8-7-8.5-12.5C24 38.5 28 35 32 35z"/>'
)
_NEZ = '<path fill="#2a1b16" d="M28.2 47.2q3.8-1.7 7.6 0-.5 4.3-3.8 5.3-3.3-1-3.8-5.3z"/>'


def dessin(taille: int) -> str:
    """Le même emblème que dans l'interface. En petit, la tête remplit davantage le carré,
    les yeux sont plus gros et sans reflet : à 16 points, un reflet n'est qu'une tache grise."""
    if taille >= 48:
        yeux = (
            '<circle fill="#1c1512" cx="21.5" cy="30" r="3"/><circle fill="#1c1512" cx="42.5" cy="30" r="3"/>'
            '<circle fill="#ffffff" cx="22.6" cy="28.9" r="1"/><circle fill="#ffffff" cx="43.6" cy="28.9" r="1"/>'
        )
        placement, coin = "translate(4.8 6.4) scale(.85)", 15
    else:
        rayon = 4.4 if taille <= 20 else 3.8
        yeux = (
            f'<circle fill="#1c1512" cx="21.5" cy="30" r="{rayon}"/>'
            f'<circle fill="#1c1512" cx="42.5" cy="30" r="{rayon}"/>'
        )
        placement, coin = "translate(1.3 2.6) scale(.96)", 13
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        f'<rect width="64" height="64" rx="{coin}" fill="#1b5b43"/>'
        f'<g transform="{placement}">{_OREILLES}{_TETE}{yeux}{_NEZ}</g></svg>'
    )


def image(taille: int) -> Image.Image:
    """Dessine à quatre fois la taille puis réduit : les bords sont plus nets en petit."""
    cote = taille * 4 if taille < 128 else taille
    flux = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(dessin(taille).encode()))
    pixbuf = GdkPixbuf.Pixbuf.new_from_stream_at_scale(flux, cote, cote, True, None)
    tampon = pixbuf.save_to_bufferv("png", [], [])[1]
    grande = Image.open(io.BytesIO(tampon)).convert("RGBA")
    return grande if cote == taille else grande.resize((taille, taille), Image.LANCZOS)


def main() -> None:
    images = [image(taille) for taille in TAILLES]
    images[-1].save(RACINE / "emballage" / "fouine.ico", format="ICO", append_images=images[:-1],
                    sizes=[(t, t) for t in TAILLES])
    image(128).save(RACINE / "fouine" / "icone.png", optimize=True)
    print("Icône écrite :", ", ".join(str(t) for t in TAILLES), "points")


if __name__ == "__main__":
    main()
