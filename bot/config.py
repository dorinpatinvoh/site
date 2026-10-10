"""Configuration du bot.

Les identifiants (numéro + mot de passe) ne sont JAMAIS écrits dans le code :
ils vivent dans le fichier `.env`, qui est ignoré par Git.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

RACINE_PROJET = Path(__file__).resolve().parent.parent
CHEMIN_ENV = RACINE_PROJET / ".env"


class ConfigIncomplete(Exception):
    """Levée quand le fichier .env ne contient pas les valeurs obligatoires."""


def charge_env(chemin: Optional[Path] = None) -> Optional[Path]:
    """Charge un fichier `.env` dans ``os.environ`` (sans dépendance externe).

    Les variables déjà présentes dans l'environnement ne sont pas écrasées,
    ce qui permet de surcharger temporairement une valeur depuis le shell.
    """
    chemin = Path(chemin) if chemin else CHEMIN_ENV
    if not chemin.is_file():
        return None

    for ligne_brute in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne_brute.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, _, valeur = ligne.partition("=")
        cle = cle.strip()
        if cle.startswith("export "):
            cle = cle[len("export ") :].strip()
        valeur = valeur.strip()
        if len(valeur) >= 2 and valeur[0] == valeur[-1] and valeur[0] in "\"'":
            valeur = valeur[1:-1]
        os.environ.setdefault(cle, valeur)
    return chemin


@dataclass
class Config:
    """Tout ce dont le bot a besoin pour tourner."""

    # --- Identifiants du compte -------------------------------------------------
    numero: str
    mot_de_passe: str

    # --- Le site ----------------------------------------------------------------
    url_site: str
    url_connexion: Optional[str] = None
    url_apres_connexion: Optional[str] = None

    # --- Sélecteurs manuels (laissés vides = détection automatique) ------------
    champ_numero: Optional[str] = None
    champ_mot_de_passe: Optional[str] = None
    bouton_connexion: Optional[str] = None

    # --- Le cerveau IA (branché plus tard) -------------------------------------
    ia_cle_api: Optional[str] = None
    ia_url_api: str = "https://api.openai.com/v1/chat/completions"
    ia_modele: str = "gpt-4o-mini"
    ia_instructions: str = ""

    # --- Réglages ---------------------------------------------------------------
    max_tours: int = 25
    delai_actions: float = 1.0
    backend: str = "http"  # "http" ou "navigateur"

    @classmethod
    def depuis_environnement(cls, chemin_env: Optional[Path] = None) -> "Config":
        charge_env(chemin_env)

        obligatoires = {
            "BOT_NUMERO": "le numéro / identifiant du compte",
            "BOT_MOT_DE_PASSE": "le mot de passe du compte",
            "BOT_URL_SITE": "l'adresse du site (ex : https://exemple.com)",
        }
        manquants = [
            f"  - {cle}  ({explication})"
            for cle, explication in obligatoires.items()
            if not os.environ.get(cle, "").strip()
        ]
        if manquants:
            source = chemin_env or CHEMIN_ENV
            raise ConfigIncomplete(
                "Configuration incomplète, valeur(s) manquante(s) :\n"
                + "\n".join(manquants)
                + f"\n\nOuvre `{source}` (ou copie `.env.example` vers `.env`) "
                "et renseigne ces valeurs."
            )

        def texte(nom: str) -> Optional[str]:
            valeur = os.environ.get(nom, "").strip()
            return valeur or None

        def entier(nom: str, defaut: int) -> int:
            try:
                return int(os.environ.get(nom, "").strip() or defaut)
            except ValueError:
                return defaut

        def decimal(nom: str, defaut: float) -> float:
            try:
                return float(os.environ.get(nom, "").strip().replace(",", ".") or defaut)
            except ValueError:
                return defaut

        return cls(
            numero=os.environ["BOT_NUMERO"].strip(),
            mot_de_passe=os.environ["BOT_MOT_DE_PASSE"],
            url_site=os.environ["BOT_URL_SITE"].strip().rstrip("/"),
            url_connexion=texte("BOT_URL_CONNEXION"),
            url_apres_connexion=texte("BOT_URL_APRES_CONNEXION"),
            champ_numero=texte("BOT_CHAMP_NUMERO"),
            champ_mot_de_passe=texte("BOT_CHAMP_MOT_DE_PASSE"),
            bouton_connexion=texte("BOT_BOUTON_CONNEXION"),
            ia_cle_api=texte("IA_CLE_API"),
            ia_url_api=os.environ.get("IA_URL_API", "").strip()
            or "https://api.openai.com/v1/chat/completions",
            ia_modele=os.environ.get("IA_MODELE", "").strip() or "gpt-4o-mini",
            ia_instructions=os.environ.get("IA_INSTRUCTIONS", "").strip(),
            max_tours=entier("BOT_MAX_TOURS", 25),
            delai_actions=decimal("BOT_DELAI_ACTIONS", 1.0),
            backend=(os.environ.get("BOT_BACKEND", "").strip() or "http").lower(),
        )
