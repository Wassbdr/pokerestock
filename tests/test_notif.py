import json
from datetime import datetime

from pokerestock import resume, tableau
from pokerestock.config import Config
from pokerestock.etat import Memoire
from pokerestock.models import PARIS, Alerte, Produit
from pokerestock.notif import NotifieurMulti, NotifieurNtfy, NotifieurConsole, Notifieur, depuis_environnement, priorite


class FausseSession:
    def __init__(self, ok=True):
        self.ok, self.envois = ok, []

    def post(self, url, json=None, headers=None, timeout=None):
        self.envois.append((url, json, headers))
        session = self

        class R:
            def raise_for_status(self):
                if not session.ok:
                    raise RuntimeError("HTTP 500")

        return R()


def alerte(**kw):
    base = dict(type="restock", titre="EN STOCK : Bundle", message="JouéClub · 39,99 €", url="https://x/fiche", chaud=True)
    base.update(kw)
    return Alerte(**base)


def test_ntfy_priorite_max_et_lien_cliquable():
    s = FausseSession()
    assert NotifieurNtfy("mon-topic", session=s).envoyer(alerte())
    url, corps, _ = s.envois[0]
    assert url == "https://ntfy.sh"
    assert corps["topic"] == "mon-topic" and corps["priority"] == 5
    assert corps["click"] == "https://x/fiche"
    assert corps["actions"][0]["url"] == "https://x/fiche"
    assert "EN STOCK" in corps["title"]


def test_priorites():
    assert priorite(alerte(chaud=False)) == 4
    assert priorite(alerte(type="illisible", chaud=True)) == 2
    assert priorite(alerte(type="signal_secours", chaud=True)) == 5


def test_multi_echec_canal_reel(monkeypatch):
    monkeypatch.setattr("pokerestock.notif.time.sleep", lambda s: None)
    multi = NotifieurMulti([NotifieurConsole(), NotifieurNtfy("t", session=FausseSession(ok=False))])
    assert multi.envoyer(alerte()) is False


def test_canaux_depuis_environnement():
    m = depuis_environnement(env={"NTFY_TOPIC": "t", "TELEGRAM_TOKEN": "a", "TELEGRAM_CHAT_ID": "1"})
    assert [c.nom for c in m.canaux] == ["console", "ntfy", "telegram"]
    assert [c.nom for c in depuis_environnement(simulation=True, env={"NTFY_TOPIC": "t"}).canaux] == ["console"]


class Echoue(Notifieur):
    nom = "ntfy"

    def __init__(self):
        self.ok = False
        self.recues = []

    def envoyer(self, a):
        self.recues.append(a)
        return self.ok


def test_alerte_non_envoyee_remise_en_file_puis_renvoyee(tmp_path):
    from tests.test_moteur import JC, monter
    from tests.conftest import page

    m, mem, _, h, client = monter(tmp_path, {JC: (200, page("proximis/joueclub_en_stock.html"))})
    canal = Echoue()
    m.notifieur = canal
    m.passage()
    assert len(mem.en_attente) == 1
    canal.ok = True
    h.t += 30
    m.passage()  # domaine pas encore revisitable, mais la file est retentée
    assert mem.en_attente == []
    assert canal.recues[-1].titre.startswith("(retard) ")


def _config():
    return Config([Produit(id="b", nom="Bundle 30 ans", plafond=39.99, marge=10, priorite="chaud")], {"joueclub": {"nom": "JouéClub"}}, {}, {})


def test_resume_quotidien(tmp_path):
    mem = Memoire(tmp_path)
    maintenant = datetime(2026, 10, 7, 8, 5, tzinfo=PARIS)
    ev = {"heure": "2026-10-07T03:00:00+02:00", "evenement": "changement", "produit": "b", "enseigne": "joueclub", "avant": "rupture", "apres": "en_stock", "prix": 39.99}
    (tmp_path / "historique.jsonl").write_text(json.dumps(ev) + "\n")
    mem.fiches["k"] = {"produit": "b", "enseigne": "joueclub", "etat": "en_stock", "prix": 39.99}
    mem.illisibles["www.fnac.com"] = {"enseigne": "Fnac", "raison": "HTTP 403", "depuis": "x"}
    a = resume.construire(_config(), mem, maintenant)
    assert a.type == "resume"
    assert "rupture → EN STOCK" in a.message
    assert "Fnac" in a.message and "Disponible maintenant" in a.message
    assert resume.est_l_heure(mem, maintenant)
    mem.data["dernier_resume"] = "2026-10-07"
    assert not resume.est_l_heure(mem, maintenant)
    assert not resume.est_l_heure(Memoire(tmp_path / "autre"), datetime(2026, 10, 7, 7, 59, tzinfo=PARIS))


def test_tableau_de_bord(tmp_path):
    mem = Memoire(tmp_path)
    mem.fiches["k"] = {"produit": "b", "enseigne": "joueclub", "etat": "en_stock", "prix": 39.99, "url": "https://x/<script>", "verifie": "2026-10-07T10:00:00+02:00", "detail": ""}
    chemin = tableau.generer(_config(), mem, tmp_path / "docs")
    contenu = chemin.read_text()
    assert "Bundle 30 ans" in contenu and "EN STOCK" in contenu and "JouéClub" in contenu
    assert "<script>" not in contenu  # échappement
    assert json.loads((tmp_path / "docs" / "etat.json").read_text())["fiches"][0]["prix"] == 39.99
