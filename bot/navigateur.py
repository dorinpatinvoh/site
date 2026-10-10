"""Backend « navigateur » : pilote un vrai Chromium via Playwright.

Utile uniquement si le site refuse une simple requête HTTP (JavaScript
obligatoire, Cloudflare, CAPTCHA…). Par défaut le bot utilise le backend HTTP,
plus léger.

    pip install playwright
    playwright install chromium
    # puis dans le .env :  BOT_BACKEND=navigateur

/!\\ Ce module n'a pas pu être exécuté dans l'environnement de développement
(sandbox sans accès au dépôt de navigateurs Playwright) : il est écrit pour
respecter exactement la même interface que ``connexion.Session`` mais mérite un
premier essai chez toi avant de s'y fier.
"""

from __future__ import annotations

import re
from typing import Callable, Dict, Optional

from .config import Config
from .connexion import EchecConnexion, RapportConnexion, Session, choisir_formulaire
from .html_outils import Champ, Formulaire, parse_page

MOTS_ECHEC = re.compile(
    r"(incorrect|invalide|erreur|error|failed|échec|echec|mauvais|wrong)", re.I
)


class SessionNavigateur(Session):
    def __init__(
        self, config: Config, journal: Callable[[str], None] = print
    ) -> None:
        super().__init__(config, journal)
        self.http.close()  # le backend navigateur n'utilise pas requests

        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._navigateur = self._playwright.chromium.launch(headless=True)
        self._contexte = self._navigateur.new_context()
        self.onglet = self._contexte.new_page()

    # ------------------------------------------------------------------ requêtes
    def get(self, url: str, **_options):
        url = self._url_absolue(url)
        try:
            self.onglet.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except Exception as exc:  # pragma: no cover
            from .connexion import ErreurSite

            raise ErreurSite(f"Impossible de charger {url} : {exc}") from exc
        self._enregistre_html()
        return self

    def post(self, url: str, donnees: Dict[str, str], **_options):
        """Remplace l'envoi HTTP par une saisie + un clic dans la page."""
        for nom, valeur in donnees.items():
            self._saisir(nom, valeur)
        self._cliquer_soumission()
        self._enregistre_html()
        return self

    def _enregistre_html(self) -> None:
        self.url_courante = self.onglet.url
        self.html = self.onglet.content()
        self.page = parse_page(self.html, self.url_courante)
        self._dernier_formulaire = choisir_formulaire(self.page)

    # -------------------------------------------------------------------- saisie
    def _selecteur(self, nom: str) -> str:
        return f'[name="{nom}"]'

    def _saisir(self, nom: str, valeur: str) -> None:
        try:
            self.onglet.fill(self._selecteur(nom), valeur, timeout=5_000)
        except Exception:
            try:
                self.onglet.fill(f"#{nom}", valeur, timeout=5_000)
            except Exception:
                pass

    def _cliquer_soumission(self) -> None:
        for selecteur in (
            'button[type="submit"]',
            'input[type="submit"]',
            "form button",
        ):
            try:
                self.onglet.click(selecteur, timeout=5_000)
                self.onglet.wait_for_load_state("domcontentloaded", timeout=15_000)
                return
            except Exception:
                continue

    # ----------------------------------------------------------------- connexion
    def connexion(self) -> RapportConnexion:
        url_connexion = self.trouve_page_connexion()
        formulaire: Optional[Formulaire] = choisir_formulaire(self.page)
        if formulaire is None:
            raise EchecConnexion(
                f"Aucun formulaire trouvé sur {url_connexion} (backend navigateur)."
            )

        from .connexion import devine_champs

        champ_numero, champ_mdp = devine_champs(
            formulaire, self.config.champ_numero, self.config.champ_mot_de_passe
        )
        if champ_numero is None or champ_mdp is None:
            raise EchecConnexion(
                "Champs numéro / mot de passe introuvables. "
                "Renseigne BOT_CHAMP_NUMERO et BOT_CHAMP_MOT_DE_PASSE."
            )

        self.journal(
            f"→ Connexion navigateur sur {url_connexion} "
            f"(« {champ_numero.nom} » + « {champ_mdp.nom} »)"
        )
        self._saisir(champ_numero.nom, self.config.numero)
        self._saisir(champ_mdp.nom, self.config.mot_de_passe)
        self._cliquer_soumission()
        self._enregistre_html()

        ok = self.url_courante != url_connexion and not any(
            f.champ_mot_de_passe for f in self.page.formulaires
        )
        if not ok and MOTS_ECHEC.search(self.page.texte):
            message = "Message d'erreur affiché par le site."
        elif ok:
            message = f"Redirigé vers {self.url_courante}."
        else:
            message = "Toujours sur la page de connexion."
        self.connecte = ok
        return RapportConnexion(
            ok, message, url_connexion, formulaire, self.onglet.url and 200
        )

    # --------------------------------------------------------------- actions IA
    def remplir(self, champ: str, valeur: str) -> str:
        cible = self._resoudre_champ(champ)
        if cible is None:
            return f"Champ « {champ} » absent de la page."
        self._saisir(cible.nom, str(valeur))
        return f"Champ « {cible.nom} » rempli."

    def soumettre(self, url: Optional[str] = None) -> str:
        self._cliquer_soumission()
        self._enregistre_html()
        return f"Formulaire envoyé, page actuelle : {self.url_courante}"

    def cliquer(self, texte: str) -> str:
        for selecteur in (
            f"a:has-text('{texte}')",
            f"button:has-text('{texte}')",
            f"text={texte}",
        ):
            try:
                self.onglet.click(selecteur, timeout=5_000)
                self.onglet.wait_for_load_state("domcontentloaded", timeout=15_000)
                self._enregistre_html()
                return f"Cliqué « {texte} » → {self.url_courante}"
            except Exception:
                continue
        return f"« {texte} » introuvable dans la page."

    def _resoudre_champ(self, champ: str) -> Optional[Champ]:
        if self._dernier_formulaire is None:
            return None
        for connu in self._dernier_formulaire.champs:
            if connu.nom == champ or champ.lower() in connu.placeholder.lower():
                return connu
        return None

    def fermer(self) -> None:
        try:
            self._contexte.close()
            self._navigateur.close()
            self._playwright.stop()
        except Exception:
            pass
