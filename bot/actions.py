"""Les actions que l'IA peut ordonner au bot.

Pour ajouter une action : écris une fonction, puis enregistre-la dans ACTIONS.
Elle devient automatiquement visible par l'IA (via ``description_des_actions``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

from .connexion import Session


@dataclass
class Action:
    nom: str
    description: str
    parametres: Dict[str, str] = field(default_factory=dict)
    fonction: Optional[Callable[..., str]] = None


def _ouvrir(session: Session, url: str = "", **_: object) -> str:
    if not url:
        return "Action « ouvrir » : l'argument « url » est obligatoire."
    session.get(url)
    return f"Page ouverte : {session.url_courante} — « {session.page.titre} »"


def _lire_page(session: Session, **_: object) -> str:
    texte = session.page.texte
    return texte[:2000] or "(page vide)"


def _remplir(session: Session, champ: str = "", valeur: str = "", **_: object) -> str:
    if not champ:
        return "Action « remplir » : l'argument « champ » est obligatoire."
    return session.remplir(champ, str(valeur))


def _soumettre(session: Session, url: Optional[str] = None, **_: object) -> str:
    return session.soumettre(url)


def _cliquer(session: Session, texte: str = "", **_: object) -> str:
    if not texte:
        return "Action « cliquer » : l'argument « texte » est obligatoire."
    return session.cliquer(str(texte))


def _attendre(session: Session, secondes: float = 2, **_: object) -> str:
    try:
        pause = max(0.1, min(float(secondes), 30))
    except (TypeError, ValueError):
        pause = 2.0
    time.sleep(pause)
    return f"Attente de {pause:g} s terminée."


def _terminer(session: Session, message: str = "", **_: object) -> str:
    return str(message) or "Fin de la mission."


ACTIONS: Dict[str, Action] = {
    "ouvrir": Action(
        "ouvrir",
        "Ouvre une URL (utilise uniquement une URL présente dans l'état ou une "
        "variante évidente de l'URL courante).",
        {"url": "URL à ouvrir"},
        _ouvrir,
    ),
    "lire_page": Action(
        "lire_page",
        "Relit le contenu texte de la page courante.",
        {},
        _lire_page,
    ),
    "cliquer": Action(
        "cliquer",
        "Clique un lien ou un bouton repéré par son texte, ou valide le "
        "formulaire si le texte correspond à un bouton.",
        {"texte": "texte du lien ou du bouton"},
        _cliquer,
    ),
    "remplir": Action(
        "remplir",
        "Prépare la valeur d'un champ du formulaire (envoyé par « soumettre »).",
        {"champ": "nom du champ", "valeur": "valeur à saisir"},
        _remplir,
    ),
    "soumettre": Action(
        "soumettre",
        "Envoie le formulaire de la page courante avec les champs remplis.",
        {"url": "URL d'envoi (facultatif)"},
        _soumettre,
    ),
    "attendre": Action(
        "attendre",
        "Fait une pause, utile quand la page doit finir de charger.",
        {"secondes": "durée en secondes"},
        _attendre,
    ),
    "terminer": Action(
        "terminer",
        "Arrête le bot : l'objectif est atteint ou impossible.",
        {"message": "conclusion à afficher"},
        _terminer,
    ),
}


def description_des_actions() -> list:
    """Liste compacte des actions, injectée dans le prompt de l'IA."""
    return [
        {
            "action": action.nom,
            "description": action.description,
            "args": action.parametres,
        }
        for action in ACTIONS.values()
    ]


def executer(session: Session, nom: str, args: Dict[str, object]) -> str:
    """Exécute une action demandée par l'IA et renvoie son compte rendu."""
    action = ACTIONS.get(nom)
    if action is None or action.fonction is None:
        return f"Action « {nom} » inconnue."
    return action.fonction(session, **args)
