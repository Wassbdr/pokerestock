"""Sources de secours : agrégateurs publics lus à faible fréquence.

Elles couvrent indirectement les enseignes illisibles (Fnac, Smyths, Cdiscount…)
avec un retard de quelques minutes et une fiabilité moindre.
"""

from dataclasses import dataclass


@dataclass
class Signal:
    source: str  # dealabs, crocodeal, alertetgo
    id: str  # identifiant stable pour le dédoublonnage
    titre: str
    url: str
    prix: float | None = None
    marchand: str | None = None
    disponible: bool = True
