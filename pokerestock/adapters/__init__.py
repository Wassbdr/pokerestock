from pokerestock.adapters.amazon import AdaptateurAmazon
from pokerestock.adapters.auchan import AdaptateurAuchan
from pokerestock.adapters.base import Adaptateur
from pokerestock.adapters.jsonld import AdaptateurJsonLd
from pokerestock.adapters.navigateur import AdaptateurNavigateur
from pokerestock.adapters.proximis import AdaptateurProximis

# Nom utilisé dans config/enseignes.yaml -> classe.
ADAPTATEURS: dict[str, type[Adaptateur]] = {
    "jsonld": AdaptateurJsonLd,
    "proximis": AdaptateurProximis,
    "amazon": AdaptateurAmazon,
    "auchan": AdaptateurAuchan,
    "navigateur": AdaptateurNavigateur,  # Playwright, pour les sites rendus en JavaScript
}
