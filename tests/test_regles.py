from pokerestock import regles
from pokerestock.models import Etat, Lecture, Produit

BUNDLE = Produit(id="b", nom="Bundle", plafond=39.99, mots_cles=["bundle 30 ans"], exclure=["display"], ean="0196214145221")


def test_trop_cher():
    assert regles.etat_final(Lecture(Etat.EN_STOCK, prix=41.99), BUNDLE, {}) == Etat.TROP_CHER


def test_au_plafond_exact_ok():
    assert regles.etat_final(Lecture(Etat.EN_STOCK, prix=39.99), BUNDLE, {}) == Etat.EN_STOCK


def test_vendeur_non_officiel_cdiscount():
    lec = Lecture(Etat.EN_STOCK, prix=30, vendeur="Super Vendeur Marketplace")
    assert regles.etat_final(lec, BUNDLE, {"vendeurs_officiels": ["Cdiscount"]}) == Etat.MARKETPLACE
    lec.vendeur = "Cdiscount"
    assert regles.etat_final(lec, BUNDLE, {"vendeurs_officiels": ["Cdiscount"]}) == Etat.EN_STOCK


def test_rupture_reste_rupture_meme_trop_cher():
    assert regles.etat_final(Lecture(Etat.RUPTURE, prix=99), BUNDLE, {}) == Etat.RUPTURE


def test_dedoublonnage():
    assert regles.doit_alerter(None, Etat.EN_STOCK, 39.99)
    assert not regles.doit_alerter({"etat": "en_stock", "prix": 39.99}, Etat.EN_STOCK, 39.99)
    assert regles.doit_alerter({"etat": "rupture", "prix": 39.99}, Etat.EN_STOCK, 39.99)
    assert regles.doit_alerter({"etat": "en_stock", "prix": 39.99}, Etat.EN_STOCK, 35.00)  # baisse de prix
    assert not regles.doit_alerter(None, Etat.RUPTURE, 10)
    assert not regles.doit_alerter(None, Etat.TROP_CHER, 50)


def test_correspondance_mots_cles():
    assert BUNDLE.correspond("Bundle Pokémon 30 ans - 6 boosters")
    assert BUNDLE.correspond("Lot réf. 0196214145221")
    assert not BUNDLE.correspond("Display Bundle 30 ans")
    assert not BUNDLE.correspond("Mini Tin 30 ans")
    tin = Produit(id="t", nom="Tin", plafond=15, mots_cles=["mini tin 30 ans"], exclure=["tin"])
    assert not tin.correspond("Mini Tin 30 ans")
    assert Produit(id="x", nom="x", plafond=1, mots_cles=["destination"], exclure=["tin"]).correspond("destination")


def test_ordinaux_harmonises():
    tin = Produit(id="t", nom="Tin", plafond=15, mots_cles=["mini tin 30e anniversaire"])
    assert tin.correspond("pokemon 30eme anniversaire mini tin")
    assert tin.correspond("Mini Tin Pokémon 30ᵉ Anniversaire")
    assert tin.correspond("mini-tin-30ieme-anniversaire")
