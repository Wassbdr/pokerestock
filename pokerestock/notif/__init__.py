"""Notifications : console, ntfy (push), e-mail (SMTP), Telegram.

Les canaux sont activés par variables d'environnement (secrets GitHub ou
fichier .env en local) :
    NTFY_TOPIC [NTFY_SERVER] [NTFY_TOKEN]
    SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD EMAIL_TO
    TELEGRAM_TOKEN TELEGRAM_CHAT_ID
"""

from __future__ import annotations

import logging
import os
import smtplib
import time
from email.message import EmailMessage

import requests

from pokerestock.models import Alerte

log = logging.getLogger("pokerestock.alertes")

LIBELLES = {
    "en_stock": "EN STOCK",
    "precommande": "PRÉCOMMANDE",
    "invitation": "INVITATION AMAZON",
    "rupture": "rupture",
    "trop_cher": "trop cher",
    "marketplace": "vendeur tiers",
    "illisible": "illisible",
}

# Priorité ntfy : 5 = max (sonne même en mode silencieux selon réglages du téléphone).
PRIORITES = {"restock": 4, "nouvelle_fiche": 4, "signal_secours": 3, "illisible": 2, "de_nouveau_lisible": 2, "resume": 3, "test": 3}
TAGS = {
    "restock": ["rotating_light", "shopping_cart"],
    "nouvelle_fiche": ["new"],
    "signal_secours": ["mag"],
    "illisible": ["warning"],
    "de_nouveau_lisible": ["white_check_mark"],
    "resume": ["newspaper"],
    "test": ["test_tube"],
}


def euros(prix: float | None) -> str:
    if prix is None:
        return "prix non lu"
    return f"{prix:.2f} €".replace(".", ",")


def heure_courte(iso: str) -> str:
    return iso[11:16] if len(iso) >= 16 else iso


def priorite(alerte: Alerte) -> int:
    p = PRIORITES.get(alerte.type, 3)
    if alerte.chaud and alerte.type in ("restock", "nouvelle_fiche", "signal_secours"):
        p = 5
    return p


class Notifieur:
    nom = "?"

    def envoyer(self, alerte: Alerte) -> bool:
        raise NotImplementedError


class NotifieurConsole(Notifieur):
    nom = "console"

    def __init__(self, simulation: bool = False):
        self.simulation = simulation
        self.envoyees: list[Alerte] = []

    def envoyer(self, alerte: Alerte) -> bool:
        prefixe = "[SIMULATION, non envoyée] " if self.simulation else ""
        marque = "!!! " if alerte.chaud else ""
        log.warning("%s%s%s\n    %s\n    %s", prefixe, marque, alerte.titre, alerte.message.replace("\n", "\n    "), alerte.url or "")
        self.envoyees.append(alerte)
        return True


def _avec_essais(f, essais: int = 3) -> bool:
    for i in range(essais):
        try:
            f()
            return True
        except Exception as e:  # réseau, quota…
            log.warning("envoi échoué (essai %d/%d) : %s", i + 1, essais, e)
            time.sleep(2 * (i + 1))
    return False


class NotifieurNtfy(Notifieur):
    nom = "ntfy"

    def __init__(self, topic: str, serveur: str = "https://ntfy.sh", token: str | None = None, session=None):
        self.topic = topic
        self.serveur = serveur.rstrip("/")
        self.token = token
        self.session = session or requests.Session()

    def charge(self, alerte: Alerte) -> dict:
        corps = {
            "topic": self.topic,
            "title": alerte.titre,
            "message": f"{alerte.message}\n{heure_courte(alerte.heure)}",
            "priority": priorite(alerte),
            "tags": TAGS.get(alerte.type, []),
        }
        if alerte.url:
            corps["click"] = alerte.url
            corps["actions"] = [{"action": "view", "label": "Ouvrir la fiche", "url": alerte.url, "clear": True}]
        return corps

    def envoyer(self, alerte: Alerte) -> bool:
        entetes = {"Authorization": f"Bearer {self.token}"} if self.token else {}

        def f():
            r = self.session.post(self.serveur, json=self.charge(alerte), headers=entetes, timeout=15)
            r.raise_for_status()

        return _avec_essais(f)


class NotifieurEmail(Notifieur):
    nom = "e-mail"

    def __init__(self, hote: str, port: int, utilisateur: str, mot_de_passe: str, destinataire: str):
        self.hote, self.port = hote, port
        self.utilisateur, self.mot_de_passe = utilisateur, mot_de_passe
        self.destinataire = destinataire

    def message(self, alerte: Alerte) -> EmailMessage:
        m = EmailMessage()
        m["Subject"] = ("[URGENT] " if priorite(alerte) == 5 else "") + f"[PokeRestock] {alerte.titre}"
        m["From"] = self.utilisateur
        m["To"] = self.destinataire
        corps = alerte.message + (f"\n\n{alerte.url}" if alerte.url else "") + f"\n\n{alerte.heure}"
        m.set_content(corps)
        return m

    def envoyer(self, alerte: Alerte) -> bool:
        def f():
            if self.port == 465:
                s = smtplib.SMTP_SSL(self.hote, self.port, timeout=20)
            else:
                s = smtplib.SMTP(self.hote, self.port, timeout=20)
                s.starttls()
            with s:
                s.login(self.utilisateur, self.mot_de_passe)
                s.send_message(self.message(alerte))

        return _avec_essais(f)


class NotifieurTelegram(Notifieur):
    nom = "telegram"

    def __init__(self, token: str, chat_id: str, session=None):
        self.token, self.chat_id = token, chat_id
        self.session = session or requests.Session()

    def envoyer(self, alerte: Alerte) -> bool:
        texte = f"{'🚨 ' if priorite(alerte) == 5 else ''}{alerte.titre}\n{alerte.message}" + (f"\n{alerte.url}" if alerte.url else "")

        def f():
            r = self.session.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": texte, "disable_notification": priorite(alerte) <= 2},
                timeout=15,
            )
            r.raise_for_status()

        return _avec_essais(f)


class NotifieurMulti(Notifieur):
    """Envoie sur tous les canaux. Réussi si au moins un canal a fonctionné."""

    nom = "multi"

    def __init__(self, canaux: list[Notifieur]):
        self.canaux = canaux
        self.envoyees: list[Alerte] = []

    def envoyer(self, alerte: Alerte) -> bool:
        resultats = {c.nom: c.envoyer(alerte) for c in self.canaux}
        reels = [ok for nom, ok in resultats.items() if nom != "console"]
        reussi = any(reels) if reels else True
        if reussi:
            self.envoyees.append(alerte)
        return reussi


def depuis_environnement(simulation: bool = False, env: dict | None = None) -> NotifieurMulti:
    env = os.environ if env is None else env
    canaux: list[Notifieur] = [NotifieurConsole(simulation=simulation)]
    if not simulation:
        if env.get("NTFY_TOPIC"):
            canaux.append(NotifieurNtfy(env["NTFY_TOPIC"], env.get("NTFY_SERVER") or "https://ntfy.sh", env.get("NTFY_TOKEN") or None))
        if env.get("SMTP_HOST") and env.get("EMAIL_TO"):
            canaux.append(
                NotifieurEmail(env["SMTP_HOST"], int(env.get("SMTP_PORT") or 587), env.get("SMTP_USER", ""), env.get("SMTP_PASSWORD", ""), env["EMAIL_TO"])
            )
        if env.get("TELEGRAM_TOKEN") and env.get("TELEGRAM_CHAT_ID"):
            canaux.append(NotifieurTelegram(env["TELEGRAM_TOKEN"], env["TELEGRAM_CHAT_ID"]))
    log.info("canaux de notification : %s", ", ".join(c.nom for c in canaux))
    multi = NotifieurMulti(canaux)
    if len(canaux) == 1 and not simulation:
        # Seule la console : l'alerte est « envoyée » au journal, mais on le signale.
        log.warning("aucun canal configuré (NTFY_TOPIC, SMTP_*, TELEGRAM_*) : alertes uniquement dans le journal")
    return multi
