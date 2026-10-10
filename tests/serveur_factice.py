"""Un faux site de connexion, pour tester le bot sans dépendre d'un vrai service.

Les noms de champs sont volontairement exotiques (`msisdn`, `cle_secrete`) :
si le bot les trouve, c'est que l'auto-détection fonctionne.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

NUMERO_VALIDE = "22997000000"
MOT_DE_PASSE_VALIDE = "secret123"
JETON_CSRF = "csrf-abc-123"
COOKIE_SESSION = "sésame-2026"

PAGE_ACCUEIL = """<!doctype html>
<html lang="fr"><head><title>Portail Démo</title></head>
<body>
  <h1>Portail Démo</h1>
  <p>Bienvenue sur le portail.</p>
  <a href="/connexion">Se connecter</a>
  <a href="/aide">Aide</a>
</body></html>"""


def page_connexion(message: str = "") -> str:
    return f"""<!doctype html>
<html lang="fr"><head><title>Connexion au portail</title></head>
<body>
  <h1>Connexion</h1>
  <p class="alerte">{message}</p>
  <form id="form_auth" action="/auth/connexion" method="post">
    <input type="hidden" name="csrf_token" value="{JETON_CSRF}">
    <label for="msisdn">Votre numéro de téléphone</label>
    <input type="text" id="msisdn" name="msisdn" placeholder="Ex : 22997000000"
           autocomplete="tel">
    <label for="cle_secrete">Mot de passe</label>
    <input type="password" id="cle_secrete" name="cle_secrete"
           placeholder="Votre mot de passe">
    <button type="submit" name="valider" value="ok">Se connecter</button>
  </form>
</body></html>"""


PAGE_TABLEAU = """<!doctype html>
<html lang="fr"><head><title>Tableau de bord</title></head>
<body>
  <h1>Bienvenue Dorin</h1>
  <p>Tu es connecté sur ton espace privé.</p>
  <ul>
    <li>Solde : 12 500 FCFA</li>
    <li>Messages non lus : 3</li>
  </ul>
  <a href="/messages">Voir les messages</a>
  <a href="/deconnexion">Se déconnecter</a>
</body></html>"""


class Gestionnaire(BaseHTTPRequestHandler):
    server_version = "PortailDemo/1.0"

    def log_message(self, *args) -> None:  # silence dans les tests
        pass

    # ------------------------------------------------------------- utilitaires
    def _envoie(self, code: int, corps: str, entetes=None) -> None:
        donnees = corps.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(donnees)))
        for cle, valeur in (entetes or {}).items():
            self.send_header(cle, valeur)
        self.end_headers()
        self.wfile.write(donnees)

    def _est_connecte(self) -> bool:
        return f"session={COOKIE_SESSION}" in (self.headers.get("Cookie") or "")

    # ------------------------------------------------------------------- GET
    def do_GET(self) -> None:
        chemin = urlparse(self.path).path

        if chemin == "/":
            self._envoie(200, PAGE_ACCUEIL)
        elif chemin == "/connexion":
            self._envoie(200, page_connexion())
        elif chemin == "/tableau":
            if self._est_connecte():
                self._envoie(200, PAGE_TABLEAU)
            else:
                self._envoie(302, "", {"Location": "/connexion"})
        elif chemin == "/messages":
            if self._est_connecte():
                self._envoie(
                    200,
                    "<html><head><title>Messages</title></head><body>"
                    "<h1>Boîte de réception</h1><p>3 messages non lus.</p>"
                    "</body></html>",
                )
            else:
                self._envoie(302, "", {"Location": "/connexion"})
        else:
            self._envoie(404, "<html><body><h1>404</h1></body></html>")

    # ------------------------------------------------------------------ POST
    def do_POST(self) -> None:
        chemin = urlparse(self.path).path
        if chemin != "/auth/connexion":
            self._envoie(404, "<html><body><h1>404</h1></body></html>")
            return

        longueur = int(self.headers.get("Content-Length") or 0)
        brut = self.rfile.read(longueur).decode("utf-8")
        champs = {c: v[0] for c, v in parse_qs(brut).items()}

        if champs.get("csrf_token") != JETON_CSRF:
            self._envoie(400, "<html><body><h1>Jeton CSRF invalide</h1></body></html>")
            return

        if (
            champs.get("msisdn") == NUMERO_VALIDE
            and champs.get("cle_secrete") == MOT_DE_PASSE_VALIDE
        ):
            self._envoie(
                302,
                "",
                {
                    "Location": "/tableau",
                    "Set-Cookie": f"session={COOKIE_SESSION}; Path=/; HttpOnly",
                },
            )
            return

        self._envoie(
            200,
            page_connexion("Identifiants incorrects, réessaie."),
        )


class ServeurFactice:
    """Serveur de test, utilisable comme gestionnaire de contexte."""

    def __init__(self) -> None:
        self._serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestionnaire)
        self._fil = threading.Thread(
            target=self._serveur.serve_forever, daemon=True
        )
        self.port = self._serveur.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "ServeurFactice":
        self._fil.start()
        return self

    def __exit__(self, *exc) -> None:
        self._serveur.shutdown()
        self._serveur.server_close()
        self._fil.join(timeout=5)
