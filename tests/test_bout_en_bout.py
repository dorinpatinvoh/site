"""Tests de bout en bout : le bot se connecte à un faux site et agit."""

from __future__ import annotations

import os

import pytest

from bot.actions import executer
from bot.config import Config, ConfigIncomplete
from bot.connexion import (
    EchecConnexion,
    Session,
    choisir_formulaire,
    devine_bouton,
    devine_champs,
)
from bot.ia import ia_decider
from bot.run import boucle_ia, masque

from .serveur_factice import MOT_DE_PASSE_VALIDE, NUMERO_VALIDE, ServeurFactice

CLEFS_ENV = ("BOT_NUMERO", "BOT_MOT_DE_PASSE", "BOT_URL_SITE", "IA_CLE_API")


@pytest.fixture(autouse=True)
def _environnement_propre(monkeypatch):
    for cle in CLEFS_ENV:
        monkeypatch.delenv(cle, raising=False)


def config_pour(url_site: str, **remplacements) -> Config:
    valeurs = {
        "numero": NUMERO_VALIDE,
        "mot_de_passe": MOT_DE_PASSE_VALIDE,
        "url_site": url_site,
        "delai_actions": 0.0,
    }
    valeurs.update(remplacements)
    return Config(**valeurs)


def journal_muet(_message: str) -> None:
    pass


# ------------------------------------------------------------------ config .env
def test_config_incomplete_signale_les_cles_manquantes(tmp_path):
    # chemin_env explicite : un `.env` local ne doit jamais fausser ce test
    with pytest.raises(ConfigIncomplete) as erreur:
        Config.depuis_environnement(tmp_path / "absent.env")
    message = str(erreur.value)
    assert "BOT_NUMERO" in message
    assert "BOT_MOT_DE_PASSE" in message
    assert "BOT_URL_SITE" in message


def test_config_lit_le_env(monkeypatch, tmp_path):
    monkeypatch.setenv("BOT_NUMERO", "22997111111")
    monkeypatch.setenv("BOT_MOT_DE_PASSE", "mot de passe avec espaces")
    monkeypatch.setenv("BOT_URL_SITE", "https://exemple.com/")
    monkeypatch.setenv("BOT_MAX_TOURS", "7")

    config = Config.depuis_environnement(tmp_path / "absent.env")
    assert config.numero == "22997111111"
    assert config.mot_de_passe == "mot de passe avec espaces"
    assert config.url_site == "https://exemple.com"  # barre finale retirée
    assert config.max_tours == 7
    assert config.backend == "http"


def test_charge_env_depuis_un_vrai_fichier(monkeypatch, tmp_path):
    """Commentaires, lignes vides et guillemets doivent être gérés."""
    from bot.config import charge_env

    for cle in CLEFS_ENV:
        monkeypatch.delenv(cle, raising=False)

    fichier = tmp_path / ".env"
    fichier.write_text(
        "# un commentaire\n"
        "\n"
        "BOT_NUMERO=22997111111\n"
        'BOT_MOT_DE_PASSE="mot avec espaces"\n'
        "BOT_URL_SITE=https://exemple.com/\n",
        encoding="utf-8",
    )

    assert charge_env(fichier) == fichier
    assert os.environ["BOT_NUMERO"] == "22997111111"
    assert os.environ["BOT_MOT_DE_PASSE"] == "mot avec espaces"

    config = Config.depuis_environnement(fichier)
    assert config.url_site == "https://exemple.com"


def test_charge_env_necrase_pas_une_variable_existante(monkeypatch, tmp_path):
    """Une variable d'environnement déjà posée prime sur le fichier .env."""
    from bot.config import charge_env

    fichier = tmp_path / ".env"
    fichier.write_text("BOT_NUMERO=valeur_du_fichier\n", encoding="utf-8")
    monkeypatch.setenv("BOT_NUMERO", "valeur_du_shell")

    charge_env(fichier)
    assert os.environ["BOT_NUMERO"] == "valeur_du_shell"


# ------------------------------------------------------------- auto-détection
def test_les_champs_sont_devines_depuis_le_html():
    with ServeurFactice() as serveur:
        session = Session(config_pour(serveur.url), journal=journal_muet)
        session.get(serveur.url + "/connexion")

        formulaire = choisir_formulaire(session.page)
        assert formulaire is not None
        assert formulaire.caches == {"csrf_token": "csrf-abc-123"}

        champ_numero, champ_mdp = devine_champs(formulaire)
        assert champ_numero.nom == "msisdn"
        assert champ_mdp.nom == "cle_secrete"

        bouton = devine_bouton(formulaire)
        assert bouton is not None and bouton.nom == "valider"
        session.fermer()


def test_la_page_de_connexion_est_trouvee_depuis_l_accueil():
    with ServeurFactice() as serveur:
        session = Session(config_pour(serveur.url), journal=journal_muet)
        url = session.trouve_page_connexion()
        assert url.endswith("/connexion")
        session.fermer()


def test_aucun_formulaire_provoque_une_erreur_explicite():
    with ServeurFactice() as serveur:
        config = config_pour(serveur.url, url_connexion=serveur.url + "/aide")
        session = Session(config, journal=journal_muet)
        with pytest.raises(EchecConnexion):
            session.connexion()
        session.fermer()


# -------------------------------------------------------------------- connexion
def test_connexion_reussie_avec_numeros_et_mot_de_passe():
    with ServeurFactice() as serveur:
        session = Session(config_pour(serveur.url), journal=journal_muet)
        rapport = session.connexion()

        assert rapport.ok, rapport.message
        assert session.connecte is True
        assert session.url_courante.endswith("/tableau")
        assert "Bienvenue Dorin" in session.page.texte
        session.fermer()


def test_connexion_refusee_si_mot_de_passe_faux():
    with ServeurFactice() as serveur:
        session = Session(
            config_pour(serveur.url, mot_de_passe="mauvais"), journal=journal_muet
        )
        rapport = session.connexion()

        assert rapport.ok is False
        assert "incorrects" in rapport.message
        assert session.connecte is False
        session.fermer()


def test_url_apres_connexion_fiabilise_le_test():
    with ServeurFactice() as serveur:
        config = config_pour(
            serveur.url, url_apres_connexion=serveur.url + "/tableau"
        )
        session = Session(config, journal=journal_muet)
        assert session.connexion().ok is True
        session.fermer()

        session = Session(
            config_pour(
                serveur.url,
                mot_de_passe="mauvais",
                url_apres_connexion=serveur.url + "/tableau",
            ),
            journal=journal_muet,
        )
        assert session.connexion().ok is False
        session.fermer()


# ----------------------------------------------------------------- actions + IA
def test_ia_sans_cle_demande_l_arret():
    config = config_pour("http://127.0.0.1:1")
    assert config.ia_cle_api is None
    decision = ia_decider(config, "peu importe", {}, [])
    assert decision.action == "terminer"


def test_executer_ouvre_et_lie_une_page():
    with ServeurFactice() as serveur:
        session = Session(config_pour(serveur.url), journal=journal_muet)
        session.connexion()

        resultat = executer(session, "cliquer", {"texte": "Voir les messages"})
        assert session.url_courante.endswith("/messages")
        assert "Boîte de réception" in resultat or "messages" in resultat

        etat = session.etat()
        assert etat["titre"] == "Messages"
        assert etat["connecte"] is True
        session.fermer()


class ReponseModeleSimule:
    """Imite la réponse d'une API compatible OpenAI."""

    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.appels = []

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.appels.append(json)
        return self

    # attributs attendus par bot.ia
    status_code = 200

    def json(self):
        """Renvoie la prochaine décision de la liste, comme le ferait l'API."""
        contenu = self.decisions[min(len(self.appels) - 1, len(self.decisions) - 1)]
        return {"choices": [{"message": {"content": contenu}}]}


def test_boucle_ia_complete_avec_un_modele_simule(monkeypatch):
    modele = ReponseModeleSimule(
        [
            '{"action": "cliquer", "args": {"texte": "Voir les messages"}, '
            '"raison": "l\'objectif parle de messages"}',
            '{"action": "terminer", "args": {"message": "3 messages non lus"}}',
        ]
    )
    import bot.ia as module_ia

    monkeypatch.setattr(module_ia.requests, "post", modele)

    with ServeurFactice() as serveur:
        config = config_pour(serveur.url, ia_cle_api="cle-de-test")
        session = Session(config, journal=journal_muet)
        assert session.connexion().ok

        code = boucle_ia(session, config, "Combien de messages non lus ?", 5)
        session.fermer()

    assert code == 0
    assert len(modele.appels) == 2
    premier_prompt = modele.appels[0]["messages"][-1]["content"]
    assert "Bienvenue Dorin" in premier_prompt  # l'état de page est bien envoyé
    assert "Voir les messages" in premier_prompt


def test_masque_le_numero_dans_les_journaux():
    assert masque("22997123456") == "*******3456"
    assert masque("12") == "**"


def test_backend_navigateur_sans_playwright_explique_quoi_installer():
    """Régression : le message d'aide doit s'afficher même quand Playwright
    n'est importé qu'au moment de créer la session."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("Playwright est installé : le message d'aide n'est pas requis")

    import bot.run as module_run

    config = config_pour("http://127.0.0.1:1", backend="navigateur")
    with pytest.raises(SystemExit) as sortie:
        module_run.construit_session(config)
    assert "playwright install chromium" in str(sortie.value)


def test_backend_http_utilise_une_session_requests():
    import bot.run as module_run

    session = module_run.construit_session(config_pour("http://127.0.0.1:1"))
    assert isinstance(session, Session)
    session.fermer()
