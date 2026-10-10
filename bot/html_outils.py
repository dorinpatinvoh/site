"""Lecture du HTML avec la bibliothèque standard uniquement (pas de bs4).

Deux sorties utiles :
  * ``parse_page()``  -> titre, texte lisible, liens, formulaires et leurs champs
  * ``texte_visible()`` -> version « texte brut » d'une page, envoyée à l'IA
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Dict, List, Optional
from urllib.parse import urljoin

_ESPACES = re.compile(r"\s+")

TYPES_SAISIS = {"text", "tel", "email", "number", "search", "password", ""}
TYPES_IGNORES = {"checkbox", "radio", "file", "image", "reset", "button", "hidden"}


@dataclass
class Champ:
    nom: str
    type: str = "text"
    placeholder: str = ""
    etiquette: str = ""
    valeur: str = ""
    autocomplete: str = ""
    position: int = 0


@dataclass
class Bouton:
    nom: str = ""
    texte: str = ""
    type: str = "submit"


@dataclass
class Formulaire:
    action: str = ""
    methode: str = "post"
    identifiant: str = ""
    champs: List[Champ] = field(default_factory=list)
    boutons: List[Bouton] = field(default_factory=list)
    caches: Dict[str, str] = field(default_factory=dict)

    @property
    def champ_mot_de_passe(self) -> Optional[Champ]:
        for champ in self.champs:
            if champ.type == "password":
                return champ
        return None


@dataclass
class Lien:
    url: str
    texte: str = ""


@dataclass
class Page:
    titre: str = ""
    texte: str = ""
    liens: List[Lien] = field(default_factory=list)
    formulaires: List[Formulaire] = field(default_factory=list)


class _Extracteur(HTMLParser):
    def __init__(self, url_base: str) -> None:
        super().__init__(convert_charrefs=True)
        self.url_base = url_base
        self.titre = ""
        self.liens: List[Lien] = []
        self.formulaires: List[Formulaire] = []
        self._morceaux_texte: List[str] = []

        self._dans_titre = False
        self._ignorer = 0  # profondeur dans <script>/<style>
        self._formulaire_courant: Optional[Formulaire] = None
        self._pseudo_formulaire = Formulaire(identifiant="(hors formulaire)")
        self._lien_courant: Optional[Lien] = None
        self._bouton_courant: Optional[Bouton] = None
        self._position = 0

    # -- utils -----------------------------------------------------------------
    def _cible(self) -> Formulaire:
        return self._formulaire_courant or self._pseudo_formulaire

    def handle_starttag(self, tag: str, attrs) -> None:
        attributs = {str(c).lower(): (v or "") for c, v in attrs}
        tag = tag.lower()

        if tag in ("script", "style", "noscript", "svg"):
            self._ignorer += 1
            return
        if tag == "title":
            self._dans_titre = True
            return

        if tag == "form":
            self._formulaire_courant = Formulaire(
                action=attributs.get("action", ""),
                methode=(attributs.get("method") or "post").lower(),
                identifiant=attributs.get("id")
                or attributs.get("name")
                or attributs.get("class", ""),
            )
            return

        if tag == "a":
            href = attributs.get("href", "").strip()
            if href and not href.startswith(("javascript:", "#", "mailto:")):
                self._lien_courant = Lien(url=urljoin(self.url_base, href))
            return

        if tag in ("input", "button", "textarea", "select"):
            self._position += 1
            forme = self._cible()
            type_champ = attributs.get("type", "").lower()

            if tag == "button":
                self._bouton_courant = Bouton(
                    nom=attributs.get("name", ""),
                    type=type_champ or "submit",
                )
                forme.boutons.append(self._bouton_courant)
                return

            nom = attributs.get("name") or attributs.get("id") or ""
            if tag == "input" and type_champ == "hidden":
                if nom:
                    forme.caches[nom] = attributs.get("value", "")
                return
            if tag == "input" and type_champ in TYPES_IGNORES:
                if type_champ in ("button", "image") or attributs.get("value"):
                    forme.boutons.append(
                        Bouton(
                            nom=nom,
                            texte=attributs.get("value", ""),
                            type="submit",
                        )
                    )
                return

            type_final = type_champ
            if tag in ("textarea", "select"):
                type_final = "text"
            forme.champs.append(
                Champ(
                    nom=nom,
                    type=type_final or "text",
                    placeholder=attributs.get("placeholder", ""),
                    autocomplete=attributs.get("autocomplete", ""),
                    valeur=attributs.get("value", ""),
                    position=self._position,
                )
            )

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("script", "style", "noscript", "svg"):
            self._ignorer = max(0, self._ignorer - 1)
        elif tag == "title":
            self._dans_titre = False
        elif tag == "form":
            if self._formulaire_courant is not None:
                self.formulaires.append(self._formulaire_courant)
            self._formulaire_courant = None
        elif tag == "a":
            if self._lien_courant is not None:
                self._lien_courant.texte = _ESPACES.sub(
                    " ", self._lien_courant.texte
                ).strip()
                self.liens.append(self._lien_courant)
            self._lien_courant = None
        elif tag == "button":
            if self._bouton_courant is not None:
                self._bouton_courant.texte = _ESPACES.sub(
                    " ", self._bouton_courant.texte
                ).strip()
            self._bouton_courant = None

    def handle_data(self, donnee: str) -> None:
        if self._ignorer:
            return
        if self._dans_titre:
            self.titre += donnee
            return
        if self._lien_courant is not None:
            self._lien_courant.texte += donnee
        if self._bouton_courant is not None:
            self._bouton_courant.texte += donnee
        self._morceaux_texte.append(donnee)

    def resultat(self) -> Page:
        if self._pseudo_formulaire.champs:
            self.formulaires.append(self._pseudo_formulaire)
        return Page(
            titre=_ESPACES.sub(" ", self.titre).strip(),
            texte=_ESPACES.sub(" ", " ".join(self._morceaux_texte)).strip(),
            liens=self.liens,
            formulaires=self.formulaires,
        )


def parse_page(html: str, url_base: str = "") -> Page:
    """Transforme du HTML en structure exploitable (formulaires, liens, texte)."""
    extracteur = _Extracteur(url_base)
    try:
        extracteur.feed(html)
        extracteur.close()
    except Exception:  # HTML bancal : on garde ce qui a pu être lu
        pass
    return extracteur.resultat()


def texte_visible(html: str, limite: int = 4000) -> str:
    """Texte lisible d'une page, tronqué pour tenir dans un prompt IA."""
    texte = parse_page(html).texte
    return texte[:limite] + ("…" if len(texte) > limite else "")
