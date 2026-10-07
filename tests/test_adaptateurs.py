import pytest

from pokerestock.adapters import AdaptateurAmazon, AdaptateurJsonLd, AdaptateurProximis
from pokerestock.adapters.base import lire_prix
from pokerestock.models import Etat
from tests.conftest import FauxClient, page


def proximis():
    return AdaptateurProximis(FauxClient(), "JouéClub")


@pytest.mark.parametrize(
    "fixture, etat, prix",
    [
        ("proximis/joueclub_rupture.html", Etat.RUPTURE, 16.99),
        ("proximis/lgr_rupture.html", Etat.RUPTURE, 16.99),
        ("proximis/joueclub_en_stock.html", Etat.EN_STOCK, 16.99),
        ("proximis/joueclub_precommande.html", Etat.PRECOMMANDE, 16.99),
    ],
)
def test_proximis_jsonld(fixture, etat, prix):
    lec = proximis().analyser(page(fixture), "https://x")
    assert lec.etat == etat
    assert lec.prix == prix
    assert lec.vendeur == "JouéClub"
    assert "TIN" in lec.titre.upper()


def test_proximis_seuil_sans_jsonld():
    lec = proximis().analyser(page("proximis/sans_jsonld_seuil.html"), "https://x")
    assert lec.etat == Etat.EN_STOCK


def test_page_vide_rendue_en_js_est_illisible():
    for ad in (proximis(), AdaptateurJsonLd(FauxClient(), "Cultura")):
        lec = ad.analyser(page("proximis/vide.html"), "https://x")
        assert lec.etat == Etat.ILLISIBLE and lec.bloque


def amazon():
    return AdaptateurAmazon(FauxClient(), "Amazon.fr")


def test_amazon_invitation_vraie_page():
    lec = amazon().analyser(page("amazon/invitation.html"), "https://x")
    assert lec.etat == Etat.INVITATION
    assert lec.prix == 35.94
    assert "30" in lec.titre


def test_amazon_en_stock_vendu_par_amazon():
    lec = amazon().analyser(page("amazon/en_stock.html"), "https://x")
    assert (lec.etat, lec.prix, lec.vendeur) == (Etat.EN_STOCK, 35.99, "Amazon")


def test_amazon_vendeur_tiers():
    lec = amazon().analyser(page("amazon/marketplace.html"), "https://x")
    assert lec.etat == Etat.MARKETPLACE
    assert lec.vendeur == "CartesCollection FR"


def test_amazon_rupture():
    assert amazon().analyser(page("amazon/rupture.html"), "https://x").etat == Etat.RUPTURE


def test_lire_fiche_bloquee_ne_plante_pas():
    url = "https://www.smythstoys.com/p/1"
    ad = AdaptateurJsonLd(FauxClient({url: (403, page("bloque/imperva.html"))}), "Smyths")
    lec = ad.lire_fiche(url)
    assert lec.etat == Etat.ILLISIBLE and lec.bloque
    assert "Imperva" in lec.detail


def test_amazon_captcha_illisible():
    url = "https://www.amazon.fr/dp/X"
    lec = AdaptateurAmazon(FauxClient({url: (200, page("amazon/captcha.html"))}), "Amazon.fr").lire_fiche(url)
    assert lec.etat == Etat.ILLISIBLE and lec.bloque


@pytest.mark.parametrize(
    "texte, attendu",
    [("35,94€", 35.94), ("1 234,50 €", 1234.5), ("41.99", 41.99), (41.99, 41.99), ("Gratuit", None), (None, None)],
)
def test_lire_prix(texte, attendu):
    assert lire_prix(texte) == attendu


def test_auchan_recherche_vraie_page():
    from pokerestock.adapters import AdaptateurAuchan

    t = AdaptateurAuchan(FauxClient(), "Auchan").analyser_recherche(page("auchan/recherche.html"), "https://www.auchan.fr/recherche?text=x")
    assert len(t) == 3
    monopoly = [x for x in t if "Monopoly" in x.titre][0]
    assert monopoly.url == "https://www.auchan.fr/hasbro-jeu-monopoly-pokemon/pr-C1821371"
    assert monopoly.prix == 24.99 and "Vendu par Auchan" in monopoly.titre


def test_microdata_carte_auchan():
    from pokerestock.adapters.jsonld import lecture_depuis_microdata

    lec = lecture_depuis_microdata(page("auchan/recherche.html"), "Auchan")
    assert lec.etat == Etat.EN_STOCK and lec.prix is not None


def test_leclerc_aggregate_offer():
    ad = AdaptateurJsonLd(FauxClient(), "E.Leclerc")
    lec = ad.analyser(page("leclerc/indisponible.html"), "https://x")
    assert lec.etat == Etat.RUPTURE
    lec = ad.analyser(page("leclerc/disponible.html"), "https://x")
    assert (lec.etat, lec.prix) == (Etat.EN_STOCK, 36.99)
    assert "non vérifié" in lec.vendeur


def test_auchan_fiche_vendeur():
    from pokerestock import regles
    from pokerestock.adapters import AdaptateurAuchan
    from pokerestock.models import Produit

    ad = AdaptateurAuchan(FauxClient(), "Auchan")
    p = Produit(id="x", nom="x", plafond=100)
    lec = ad.analyser(page("auchan/fiche_vendu_par_auchan.html"), "https://x")
    assert (lec.etat, lec.prix, lec.vendeur) == (Etat.EN_STOCK, 24.99, "Auchan")
    assert regles.etat_final(lec, p, {"vendeurs_officiels": ["Auchan"]}) == Etat.EN_STOCK
    lec = ad.analyser(page("auchan/fiche_marketplace.html"), "https://x")
    assert lec.vendeur == "2KINGS"
    assert regles.etat_final(lec, p, {"vendeurs_officiels": ["Auchan"]}) == Etat.MARKETPLACE
