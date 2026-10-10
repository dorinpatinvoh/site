"""Démo locale : lance le bot contre un faux site, sans identifiants réels.

    python demo.py                # connexion + mission (IA non branchée)
    python demo.py --verifier     # teste juste la connexion
    python demo.py --mauvais-mdp  # montre le message quand le site refuse

Le faux site utilise des noms de champs exotiques (`msisdn`, `cle_secrete`) :
si la connexion passe, c'est que l'auto-détection fonctionne.
"""

from __future__ import annotations

import os
import sys

from bot.run import main
from tests.serveur_factice import MOT_DE_PASSE_VALIDE, NUMERO_VALIDE, ServeurFactice


def demo() -> int:
    mauvais_mdp = "--mauvais-mdp" in sys.argv
    arguments = [a for a in sys.argv[1:] if a != "--mauvais-mdp"]

    with ServeurFactice() as serveur:
        print(f"Site de démonstration lancé sur {serveur.url}\n")
        os.environ["BOT_NUMERO"] = NUMERO_VALIDE
        os.environ["BOT_MOT_DE_PASSE"] = "faux" if mauvais_mdp else MOT_DE_PASSE_VALIDE
        os.environ["BOT_URL_SITE"] = serveur.url
        os.environ["BOT_DELAI_ACTIONS"] = "0"

        return main(
            arguments
            or [
                "--objectif",
                "Va dans les messages et dis combien sont non lus, puis termine.",
            ]
        )


if __name__ == "__main__":
    raise SystemExit(demo())
