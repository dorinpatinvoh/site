"""Connexion au site avec numéro + mot de passe.

Le script ne connaît pas le site à l'avance : il ouvre la page de connexion,
trouve tout seul le champ « numéro », le champ « mot de passe » et le bouton,
puis envoie le formulaire. Chaque étape peut être forcée depuis le `.env`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests

from .config import Config
from .html_outils import Bouton, Champ, Formulaire, Page, parse_page

DELAI_REQUETE = 25
EN_TETES = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "fr,fr-FR;q=0.9,en;q=0.8",
}

CHEMINS_CONNEXION = [
    "/connexion",
    "/login",
    "/signin",
    "/sign-in",
    "/se-connecter",
    "/auth/login",
    "/auth/connexion",
    "/compte/connexion",
    "/account/login",
    "/user/login",
]

MOTS_LIEN_CONNEXION = re.compile(
    r"(connexion|connect|log[\s_-]?in|sign[\s_-]?in|s'identifier|se connecter|auth)",
    re.I,
)

# Mots-clés qui trahissent le champ « numéro / identifiant ».
MOTS_NUMERO_FORTS = re.compile(
    r"(phone|tel|mobile|numero|num[ée]ro|number|msisdn|whatsapp|cellulaire)", re.I
)
MOTS_NUMERO_FAIBLES = re.compile(
    r"(user|username|login|identifiant|email|e-?mail|pseudo|compte|account|matricule|id)",
    re.I,
)
MOTS_MOT_DE_PASSE = re.compile(
    r"(password|passwd|pass|pwd|mdp|mot[\s_-]?de[\s_-]?passe|secret|cle|key)", re.I
)
MOTS_BOUTON = re.compile(
    r"(connexion|connect|log[\s_-]?in|sign[\s_-]?in|valider|envoyer|continuer|submit|"
    r"s'identifier|se connecter|entrer)",
    re.I,
)
MOTS_ECHEC = re.compile(
    r"(incorrect|invalide|invalid|erron[ée]|erreur|error|failed|failure|échec|echec|"
    r"mauvais|wrong|not found|introuvable|identifiants)",
    re.I,
)


class ErreurSite(Exception):
    """Problème réseau ou page inaccessible."""


class EchecConnexion(Exception):
    """Le site a refusé les identifiants (ou le formulaire n'a pas été trouvé)."""


@dataclass
class RapportConnexion:
    ok: bool
    message: str
    url_connexion: str = ""
    formulaire: Optional[Formulaire] = None
    code_http: Optional[int] = None

    def __str__(self) -> str:  # pragma: no cover - affichage
        return f"{'OK' if self.ok else 'ÉCHEC'} - {self.message}"


def _texte_champ(champ: Champ) -> str:
    return " ".join(
        [champ.nom, champ.placeholder, champ.autocomplete, champ.etiquette]
    )


def devine_champs(
    formulaire: Formulaire,
    champ_numero_force: Optional[str] = None,
    champ_mdp_force: Optional[str] = None,
) -> tuple[Optional[Champ], Optional[Champ]]:
    """Retourne (champ numéro, champ mot de passe) d'un formulaire."""

    def par_nom(voulu: Optional[str]) -> Optional[Champ]:
        if not voulu:
            return None
        for champ in formulaire.champs:
            if champ.nom == voulu or champ.nom.lower() == voulu.lower():
                return champ
            if champ.placeholder and voulu.lower() in champ.placeholder.lower():
                return champ
        return None

    champ_mdp = par_nom(champ_mdp_force)
    if champ_mdp is None:
        champ_mdp = formulaire.champ_mot_de_passe
    if champ_mdp is None:
        candidats = [
            c
            for c in formulaire.champs
            if MOTS_MOT_DE_PASSE.search(_texte_champ(c))
        ]
        champ_mdp = min(candidats, key=lambda c: c.position, default=None)

    champ_numero = par_nom(champ_numero_force)
    if champ_numero is None:
        restants = [c for c in formulaire.champs if c is not champ_mdp]
        if restants:
            def score(champ: Champ) -> tuple:
                texte = _texte_champ(champ)
                fort = 0 if MOTS_NUMERO_FORTS.search(texte) else 1
                faible = 0 if MOTS_NUMERO_FAIBLES.search(texte) else 1
                return (fort, faible, champ.position)

            champ_numero = min(restants, key=score)

    return champ_numero, champ_mdp


def devine_bouton(
    formulaire: Formulaire, bouton_force: Optional[str] = None
) -> Optional[Bouton]:
    """Retourne le bouton qui valide le formulaire (souvent optionnel)."""
    if not formulaire.boutons:
        return None

    if bouton_force:
        for bouton in formulaire.boutons:
            if bouton_force.lower() in (bouton.nom + " " + bouton.texte).lower():
                return bouton

    for bouton in formulaire.boutons:
        if bouton.type == "submit" and (bouton.nom or bouton.texte):
            return bouton
    for bouton in formulaire.boutons:
        if MOTS_BOUTON.search(bouton.texte or bouton.nom):
            return bouton
    return formulaire.boutons[0]


def choisir_formulaire(page: Page) -> Optional[Formulaire]:
    """Choisit le formulaire de connexion parmi ceux de la page."""
    candidats = [f for f in page.formulaires if f.champs]
    if not candidats:
        return None

    def score(formulaire: Formulaire) -> tuple:
        identifiant = (
            formulaire.identifiant + " " + formulaire.action
        )
        a_mot_de_passe = 0 if formulaire.champ_mot_de_passe else 1
        parle_connexion = 0 if MOTS_LIEN_CONNEXION.search(identifiant) else 1
        return (a_mot_de_passe, parle_connexion, -len(formulaire.champs))

    return sorted(candidats, key=score)[0]


def est_page_de_connexion(page: Page) -> bool:
    return any(f.champ_mot_de_passe for f in page.formulaires)


class Session:
    """Une session HTTP connectée au site."""

    def __init__(
        self, config: Config, journal: Callable[[str], None] = print
    ) -> None:
        self.config = config
        self.journal = journal
        self.http = requests.Session()
        self.http.headers.update(EN_TETES)
        self.url_courante: str = config.url_site
        self.html: str = ""
        self.page: Page = Page()
        self.connecte: bool = False
        self.champs_en_attente: Dict[str, str] = {}
        self._dernier_formulaire: Optional[Formulaire] = None

    # ------------------------------------------------------------------ requêtes
    def get(self, url: str, **options) -> requests.Response:
        url = self._url_absolue(url)
        try:
            reponse = self.http.get(url, timeout=DELAI_REQUETE, **options)
        except requests.RequestException as exc:
            raise ErreurSite(f"Impossible de charger {url} : {exc}") from exc
        self._enregistre(reponse)
        return reponse

    def post(self, url: str, donnees: Dict[str, str], **options) -> requests.Response:
        url = self._url_absolue(url)
        try:
            reponse = self.http.post(
                url, data=donnees, timeout=DELAI_REQUETE, **options
            )
        except requests.RequestException as exc:
            raise ErreurSite(f"Impossible d'envoyer le formulaire à {url} : {exc}") from exc
        self._enregistre(reponse)
        return reponse

    def _url_absolue(self, url: str) -> str:
        if url.startswith(("http://", "https://")):
            return url
        return urljoin(self.url_courante or self.config.url_site, url)

    def _enregistre(self, reponse: requests.Response) -> None:
        self.url_courante = str(reponse.url)
        self.html = reponse.text
        self.page = parse_page(self.html, self.url_courante)
        self._dernier_formulaire = choisir_formulaire(self.page)

    # ---------------------------------------------------------------- connexion
    def trouve_page_connexion(self) -> str:
        """Localise la page de connexion : config > lien sur l'accueil > chemins connus."""
        if self.config.url_connexion:
            self.get(self.config.url_connexion)
            return self.url_courante

        self.get(self.config.url_site)
        if est_page_de_connexion(self.page):
            return self.url_courante

        for lien in self.page.liens:
            if MOTS_LIEN_CONNEXION.search(lien.url + " " + lien.texte):
                self.get(lien.url)
                if est_page_de_connexion(self.page):
                    return self.url_courante

        for chemin in CHEMINS_CONNEXION:
            url = urljoin(self.config.url_site + "/", chemin.lstrip("/"))
            try:
                reponse = self.get(url)
            except ErreurSite:
                continue
            if reponse.status_code == 200 and est_page_de_connexion(self.page):
                return self.url_courante

        raise EchecConnexion(
            "Page de connexion introuvable. Renseigne BOT_URL_CONNEXION dans le .env."
        )

    def connexion(self) -> RapportConnexion:
        """Se connecte avec le numéro et le mot de passe du .env."""
        url_connexion = self.trouve_page_connexion()
        formulaire = choisir_formulaire(self.page)
        if formulaire is None:
            raise EchecConnexion(
                f"Aucun formulaire utilisable sur {url_connexion}. "
                "Vérifie BOT_URL_CONNEXION ou passe BOT_BACKEND=navigateur."
            )

        champ_numero, champ_mdp = devine_champs(
            formulaire,
            self.config.champ_numero,
            self.config.champ_mot_de_passe,
        )
        if champ_mdp is None:
            raise EchecConnexion(
                f"Champ mot de passe introuvable sur {url_connexion}. "
                "Renseigne BOT_CHAMP_MOT_DE_PASSE dans le .env."
            )
        if champ_numero is None:
            raise EchecConnexion(
                f"Champ numéro introuvable sur {url_connexion}. "
                "Renseigne BOT_CHAMP_NUMERO dans le .env."
            )

        donnees: Dict[str, str] = dict(formulaire.caches)
        donnees[champ_numero.nom] = self.config.numero
        donnees[champ_mdp.nom] = self.config.mot_de_passe

        bouton = devine_bouton(formulaire, self.config.bouton_connexion)
        if bouton and bouton.nom:
            donnees[bouton.nom] = bouton.texte or "OK"

        action = formulaire.action or url_connexion
        methode = (formulaire.methode or "post").lower()

        self.journal(
            f"→ Connexion sur {url_connexion} "
            f"(numéro : champ « {champ_numero.nom} », "
            f"mot de passe : champ « {champ_mdp.nom} »)"
        )

        cookies_avant = set(self.http.cookies.keys())
        if methode == "get":
            reponse = self.get(action, params=donnees)
        else:
            reponse = self.post(action, donnees)

        rapport = self._analyse_connexion(
            reponse, cookies_avant, url_connexion, formulaire
        )
        self.connecte = rapport.ok
        return rapport

    def _analyse_connexion(
        self,
        reponse: requests.Response,
        cookies_avant: set,
        url_connexion: str,
        formulaire: Formulaire,
    ) -> RapportConnexion:
        """Décide si la connexion a réussi (redirection, cookie, message d'erreur)."""
        nouveaux_cookies = set(self.http.cookies.keys()) - cookies_avant
        a_bouge = self.url_courante.split("?")[0] != url_connexion.split("?")[0]
        formulaire_encore_la = est_page_de_connexion(self.page)

        if self.config.url_apres_connexion:
            cible = self.get(self.config.url_apres_connexion)
            encore_formulaire = est_page_de_connexion(self.page)
            if cible.status_code == 200 and not encore_formulaire:
                return RapportConnexion(
                    True,
                    f"Page privée {self.config.url_apres_connexion} accessible.",
                    url_connexion,
                    formulaire,
                    reponse.status_code,
                )
            return RapportConnexion(
                False,
                "Identifiants refusés : la page privée reste inaccessible.",
                url_connexion,
                formulaire,
                reponse.status_code,
            )

        if reponse.status_code in (401, 403):
            return RapportConnexion(
                False,
                f"Refusé par le site (HTTP {reponse.status_code}).",
                url_connexion,
                formulaire,
                reponse.status_code,
            )

        if a_bouge and not formulaire_encore_la:
            return RapportConnexion(
                True,
                f"Redirigé vers {self.url_courante}"
                + (f" · cookie {', '.join(sorted(nouveaux_cookies))}" if nouveaux_cookies else ""),
                url_connexion,
                formulaire,
                reponse.status_code,
            )

        if nouveaux_cookies and reponse.status_code < 400:
            return RapportConnexion(
                True,
                f"Cookie de session reçu : {', '.join(sorted(nouveaux_cookies))}.",
                url_connexion,
                formulaire,
                reponse.status_code,
            )

        if formulaire_encore_la and MOTS_ECHEC.search(self.page.texte):
            extrait = MOTS_ECHEC.search(self.page.texte)
            debut = max(0, extrait.start() - 60)
            return RapportConnexion(
                False,
                "Le site a renvoyé un message d'erreur : « "
                + self.page.texte[debut : extrait.end() + 60].strip()
                + " »",
                url_connexion,
                formulaire,
                reponse.status_code,
            )

        if formulaire_encore_la:
            return RapportConnexion(
                False,
                "Toujours sur le formulaire de connexion : identifiants refusés "
                "ou formulaire mal reconnu.",
                url_connexion,
                formulaire,
                reponse.status_code,
            )

        return RapportConnexion(
            True,
            f"Réponse HTTP {reponse.status_code} sur {self.url_courante}.",
            url_connexion,
            formulaire,
            reponse.status_code,
        )

    # ------------------------------------------------------------ état pour l'IA
    def etat(self) -> Dict[str, object]:
        """Résumé de la page courante, tel qu'il est envoyé à l'IA."""
        champs: List[Dict[str, str]] = []
        if self._dernier_formulaire:
            champs = [
                {
                    "nom": c.nom,
                    "type": c.type,
                    "placeholder": c.placeholder,
                }
                for c in self._dernier_formulaire.champs
            ]
        liens = [
            {"texte": l.texte or "(sans texte)", "url": l.url}
            for l in self.page.liens[:15]
        ]
        return {
            "url": self.url_courante,
            "titre": self.page.titre,
            "connecte": self.connecte,
            "texte": self.page.texte[:2500],
            "champs_du_formulaire": champs,
            "liens_visibles": liens,
        }

    # ------------------------------------------------------- actions pour l'IA
    def remplir(self, champ: str, valeur: str) -> str:
        if self._dernier_formulaire is None:
            return "Aucun formulaire sur cette page."
        for connu in self._dernier_formulaire.champs:
            if connu.nom == champ or champ.lower() in connu.placeholder.lower():
                self.champs_en_attente[connu.nom] = valeur
                return f"Champ « {connu.nom} » prêt à être envoyé."
        return (
            f"Champ « {champ} » absent de la page. "
            f"Disponibles : {[c.nom for c in self._dernier_formulaire.champs]}"
        )

    def soumettre(self, url: Optional[str] = None) -> str:
        if self._dernier_formulaire is None:
            return "Aucun formulaire à envoyer sur cette page."
        donnees = dict(self._dernier_formulaire.caches)
        donnees.update(self.champs_en_attente)
        bouton = devine_bouton(self._dernier_formulaire)
        if bouton and bouton.nom:
            donnees[bouton.nom] = bouton.texte or "OK"
        cible = url or self._dernier_formulaire.action or self.url_courante
        reponse = self.post(cible, donnees)
        self.champs_en_attente.clear()
        return f"Formulaire envoyé à {self.url_courante} (HTTP {reponse.status_code})."

    def cliquer(self, texte: str) -> str:
        """Clique un lien ou un bouton repéré par son libellé."""
        formule = texte.lower()
        for lien in self.page.liens:
            if formule in (lien.texte or "").lower() or formule in lien.url.lower():
                self.get(lien.url)
                return f"Ouvert : {self.url_courante}"
        if self._dernier_formulaire:
            for bouton in self._dernier_formulaire.boutons:
                if formule in (bouton.texte + " " + bouton.nom).lower():
                    return self.soumettre()
        proches = [l.texte for l in self.page.liens[:10] if l.texte]
        return f"« {texte} » introuvable. Liens visibles : {proches}"

    def fermer(self) -> None:
        self.http.close()


def domaine(url: str) -> str:
    return urlparse(url).netloc
