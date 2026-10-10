"""Point d'entrée : connexion au compte puis boucle pilotée par l'IA.

    python -m bot.run                       # connexion + mission par défaut
    python -m bot.run --verifier            # teste juste la connexion
    python -m bot.run --objectif "..."      # donne une mission précise à l'IA
    python -m bot.run --tours 10            # limite le nombre d'actions
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from .actions import executer
from .config import Config, ConfigIncomplete
from .connexion import EchecConnexion, ErreurSite, Session
from .ia import ErreurIA, ia_decider

OBJECTIF_PAR_DEFAUT = (
    "Explore le compte connecté et résume ce qui s'y trouve, "
    "puis termine proprement."
)


def construit_session(config: Config) -> Session:
    """Choisit le backend : HTTP par défaut, navigateur si demandé."""
    if config.backend == "navigateur":
        try:
            from .navigateur import SessionNavigateur

            return SessionNavigateur(config)
        except ImportError as exc:  # pragma: no cover - dépend de l'installation
            raise SystemExit(
                f"Le backend « navigateur » n'a pas pu démarrer ({exc}).\n"
                "Installe Playwright :  pip install playwright && playwright install chromium\n"
                "Ou repasse en HTTP :  BOT_BACKEND=http dans le .env"
            ) from exc
    return Session(config)


def boucle_ia(
    session: Session, config: Config, objectif: str, max_tours: int
) -> int:
    historique: List[str] = []

    print(f"\n=== Mission : {objectif}\n")
    for tour in range(1, max_tours + 1):
        try:
            decision = ia_decider(config, objectif, session.etat(), historique)
        except ErreurIA as exc:
            print(f"\n✗ IA : {exc}")
            return 2

        print(f"[tour {tour}] {decision.action} {decision.args or ''}")
        if decision.raison:
            print(f"          parce que : {decision.raison}")

        resultat = executer(session, decision.action, decision.args)
        historique.append(f"{decision.action} -> {resultat[:200]}")

        if decision.action == "terminer":
            print(f"\n✓ Terminé : {resultat}")
            return 0

        if decision.action != "attendre" and config.delai_actions:
            import time

            time.sleep(config.delai_actions)

    print(f"\n⚠ Arrêt après {max_tours} tours sans conclusion de l'IA.")
    return 3


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Se connecte à un compte puis laisse l'IA piloter."
    )
    parser.add_argument(
        "--objectif",
        default=OBJECTIF_PAR_DEFAUT,
        help="mission donnée à l'IA (défaut : explorer et résumer)",
    )
    parser.add_argument(
        "--tours", type=int, default=None, help="nombre maximum d'actions"
    )
    parser.add_argument(
        "--verifier",
        action="store_true",
        help="teste uniquement la connexion, sans lancer l'IA",
    )
    arguments = parser.parse_args(argv)

    try:
        config = Config.depuis_environnement()
    except ConfigIncomplete as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1

    print(f"Site    : {config.url_site}")
    print(f"Numéro  : {masque(config.numero)}")
    print(f"Backend : {config.backend}")

    session = construit_session(config)
    try:
        try:
            rapport = session.connexion()
        except EchecConnexion as exc:
            print(f"\n✗ Connexion impossible : {exc}", file=sys.stderr)
            return 1
        except ErreurSite as exc:
            print(f"\n✗ {exc}", file=sys.stderr)
            return 1

        print(f"\n{'✓' if rapport.ok else '✗'} {rapport.message}")
        if not rapport.ok:
            print(
                "\nVérifie BOT_NUMERO / BOT_MOT_DE_PASSE, ou force les champs "
                "avec BOT_CHAMP_NUMERO et BOT_CHAMP_MOT_DE_PASSE.",
                file=sys.stderr,
            )
            return 1

        if arguments.verifier:
            print("\nConnexion validée. (--verifier : l'IA n'a pas été lancée)")
            return 0

        return boucle_ia(
            session, config, arguments.objectif, arguments.tours or config.max_tours
        )
    finally:
        session.fermer()


def masque(valeur: str) -> str:
    """N'affiche jamais le numéro en clair dans les journaux."""
    if len(valeur) <= 4:
        return "*" * len(valeur)
    return "*" * (len(valeur) - 4) + valeur[-4:]


if __name__ == "__main__":
    raise SystemExit(main())
