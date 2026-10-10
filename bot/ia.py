"""Le cerveau du bot.

Pour l'instant la fonction ``ia_decider()`` est une ébauche : elle renvoie
``terminer`` tant qu'aucune clé d'API n'est configurée. Dès que tu ajoutes
``IA_CLE_API`` dans le `.env`, la même fonction interroge un modèle compatible
OpenAI (OpenAI, Groq, Mistral, OpenRouter, ollama local…) et le modèle choisit
l'action suivante.

C'est LE fichier à personnaliser quand tu brancheras ton IA.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import requests

from .actions import ACTIONS, description_des_actions
from .config import Config

DELAI_IA = 90


class ErreurIA(Exception):
    pass


@dataclass
class Decision:
    action: str
    args: Dict[str, object] = field(default_factory=dict)
    raison: str = ""


PROMPT_SYSTEME = """Tu pilotes un bot Python déjà connecté à un site web.
À chaque tour on te donne l'état de la page (URL, titre, texte, champs, liens)
et la liste des actions possibles. Tu réponds UNIQUEMENT par un objet JSON :

{"action": "<nom d'une action>", "args": {<arguments>}, "raison": "<une phrase>"}

Règles :
- N'invente jamais d'action hors de la liste.
- N'invente jamais d'URL, de nom de champ ou de valeur absents de l'état.
- Une action par réponse. Quand l'objectif est atteint, réponds "terminer".
- Aucun texte avant ou après le JSON, aucun bloc de code."""


def _extrait_json(texte: str) -> Optional[dict]:
    """Récupère le JSON dans la réponse du modèle, même entouré de prose."""
    texte = texte.strip()
    bloc = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", texte, re.S)
    if bloc:
        texte = bloc.group(1)
    try:
        return json.loads(texte)
    except json.JSONDecodeError:
        pass
    objet = re.search(r"\{.*\}", texte, re.S)
    if objet:
        try:
            return json.loads(objet.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _valide(decision: dict) -> Decision:
    nom = str(decision.get("action", "")).strip().lower()
    if nom not in ACTIONS:
        raise ErreurIA(
            f"Action « {nom} » inconnue. Actions valables : {', '.join(ACTIONS)}"
        )
    args = decision.get("args")
    if not isinstance(args, dict):
        args = {}
    return Decision(
        action=nom,
        args={str(c): v for c, v in args.items()},
        raison=str(decision.get("raison", ""))[:300],
    )


def ia_decider(
    config: Config,
    objectif: str,
    etat: Dict[str, object],
    historique: List[str],
) -> Decision:
    """Demande au modèle quelle action jouer maintenant.

    Remplace le corps de cette fonction si tu utilises une autre IA
    (SDK propriétaire, modèle local, LangChain…). Le contrat est simple :
    renvoyer une ``Decision``.
    """
    if not config.ia_cle_api:
        return Decision(
            action="terminer",
            raison=(
                "Aucune clé IA configurée (IA_CLE_API absente du .env) : "
                "le bot s'arrête après la connexion. Branche ton IA pour qu'il "
                "agisse tout seul."
            ),
        )

    prompt_utilisateur = json.dumps(
        {
            "objectif": objectif,
            "actions_possibles": description_des_actions(),
            "historique": historique[-12:],
            "etat_page": etat,
        },
        ensure_ascii=False,
        indent=2,
    )
    messages = [
        {"role": "system", "content": PROMPT_SYSTEME},
    ]
    if config.ia_instructions:
        messages.append({"role": "system", "content": config.ia_instructions})
    messages.append({"role": "user", "content": prompt_utilisateur})

    derniere_erreur = "réponse vide"
    for tentative in range(2):
        try:
            reponse = requests.post(
                config.ia_url_api,
                headers={
                    "Authorization": f"Bearer {config.ia_cle_api}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config.ia_modele,
                    "messages": messages,
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                },
                timeout=DELAI_IA,
            )
        except requests.RequestException as exc:
            raise ErreurIA(f"Appel IA impossible : {exc}") from exc

        if reponse.status_code != 200:
            raise ErreurIA(
                f"L'API IA a répondu HTTP {reponse.status_code} : "
                f"{reponse.text[:300]}"
            )

        try:
            contenu = reponse.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise ErreurIA(f"Réponse IA illisible : {reponse.text[:300]}") from exc

        decision = _extrait_json(contenu or "")
        if decision is None:
            derniere_erreur = f"pas de JSON dans : {str(contenu)[:200]}"
            messages.append({"role": "assistant", "content": contenu or ""})
            messages.append(
                {
                    "role": "user",
                    "content": "Réponds uniquement par l'objet JSON demandé.",
                }
            )
            continue

        try:
            return _valide(decision)
        except ErreurIA as exc:
            derniere_erreur = str(exc)
            messages.append({"role": "assistant", "content": contenu or ""})
            messages.append(
                {"role": "user", "content": f"Correction : {exc}. Renvoie le JSON."}
            )

    raise ErreurIA(f"L'IA n'a pas renvoyé d'action exploitable ({derniere_erreur}).")
