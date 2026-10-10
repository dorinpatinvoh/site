# Bot de connexion piloté par IA

Un script Python qui **se connecte à un compte avec numéro + mot de passe**, puis
laisse une IA décider des actions suivantes (ouvrir une page, cliquer, remplir un
formulaire, lire le contenu, terminer).

Le bot ne connaît aucun site à l'avance : il ouvre la page de connexion,
**détecte tout seul** le champ numéro, le champ mot de passe et le bouton, puis
envoie le formulaire.

```
bot/
├── config.py        lit le .env  →  aucun identifiant dans le code
├── connexion.py     trouve la page de login, devine les champs, se connecte
├── html_outils.py   lit le HTML (stdlib uniquement, sans bs4)
├── actions.py       les actions que l'IA peut ordonner
├── ia.py            ★ LE fichier à brancher sur ton IA
├── run.py           point d'entrée : connexion puis boucle IA
└── navigateur.py    backend optionnel Chromium/Playwright (sites exigeant du JS)
```

---

## 1. Installation

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Configuration

```bash
cp .env.example .env
```

Puis édite `.env` — **3 valeurs sont obligatoires** :

```ini
BOT_NUMERO=22997000000
BOT_MOT_DE_PASSE=ton-mot-de-passe
BOT_URL_SITE=https://ton-site.com
```

`.env` est listé dans `.gitignore` : tes identifiants ne partent jamais dans Git.

Le reste est facultatif. En particulier, laisse **vides** `BOT_CHAMP_NUMERO` /
`BOT_CHAMP_MOT_DE_PASSE` : le script devine les champs. S'il se trompe sur un
site exotique, ouvre la page de connexion, regarde le `name=` des inputs dans le
code source, et renseigne-les ici.

## 3. Lancement

```bash
python -m bot.run --verifier                    # teste juste la connexion
python -m bot.run                               # connexion + mission par défaut
python -m bot.run --objectif "Relève mon solde" # mission précise
python -m bot.run --tours 10                    # limite le nombre d'actions
```

Sortie attendue :

```
Site    : https://ton-site.com
Numéro  : *******0000
Backend : http
→ Connexion sur https://ton-site.com/connexion (numéro : champ « msisdn », mot de passe : champ « cle_secrete »)

✓ Redirigé vers https://ton-site.com/tableau · cookie session
```

### Voir le bot tourner tout de suite, sans compte réel

```bash
python demo.py                # faux site local, champs volontairement exotiques
python demo.py --mauvais-mdp  # ce qu'affiche le bot quand le site refuse
```

## 4. Brancher l'IA

Ajoute ta clé dans `.env` :

```ini
IA_CLE_API=sk-...
IA_MODELE=gpt-4o-mini
IA_URL_API=https://api.openai.com/v1/chat/completions
```

Toute API **compatible OpenAI** fonctionne : OpenAI, Groq, Mistral, OpenRouter,
ou un modèle local via Ollama (`http://localhost:11434/v1/chat/completions`).

Tant que `IA_CLE_API` est vide, le bot **se connecte puis s'arrête** proprement :
tu peux donc valider la connexion avant de brancher l'IA.

L'IA reçoit à chaque tour l'état de la page (URL, titre, texte, champs, liens) et
la liste des actions, et répond par un JSON :

```json
{"action": "cliquer", "args": {"texte": "Voir les messages"}, "raison": "..."}
```

Actions disponibles : `ouvrir`, `lire_page`, `cliquer`, `remplir`, `soumettre`,
`attendre`, `terminer`. **Pour en ajouter une** : écris une fonction dans
`bot/actions.py` et enregistre-la dans le dictionnaire `ACTIONS` — elle devient
automatiquement visible par l'IA.

Pour changer de fournisseur ou de logique de décision, modifie
`ia_decider()` dans `bot/ia.py` : le contrat est simplement « renvoyer une
`Decision` ».

## 5. Si le site exige du JavaScript

Certaines pages de connexion ne marchent pas en HTTP simple. Passe alors au
backend navigateur :

```bash
pip install playwright && playwright install chromium
# dans .env :
BOT_BACKEND=navigateur
```

> `bot/navigateur.py` expose exactement la même interface que le backend HTTP,
> mais il n'a **pas pu être exécuté** dans l'environnement de développement
> (sandbox sans accès au dépôt de navigateurs Playwright). Il est donc écrit et
> testé à l'import, mais à valider chez toi au premier essai.

## 6. Tests

```bash
pip install pytest
python -m pytest -v
```

14 tests lancent un **faux site de connexion** (`tests/serveur_factice.py`, avec
des champs `msisdn` / `cle_secrete` et un jeton CSRF) et vérifient :
auto-détection des champs, connexion réussie, refus du site, message de
configuration manquante, boucle IA complète avec un modèle simulé.

## 7. Dépannage

| Symptôme | Solution |
|---|---|
| `Page de connexion introuvable` | renseigne `BOT_URL_CONNEXION` |
| `Champ numéro introuvable` | renseigne `BOT_CHAMP_NUMERO` avec le `name=` exact |
| Le site renvoie une erreur alors que le mot de passe est bon | le login passe par JavaScript → `BOT_BACKEND=navigateur` |
| `L'API IA a répondu HTTP 401` | clé `IA_CLE_API` invalide ou expirée |
| Connexion OK mais l'IA ne fait rien | `IA_CLE_API` est vide dans le `.env` |

## 8. Bonnes pratiques

- N'automatise **que tes propres comptes**, et vérifie que les conditions
  d'utilisation du site l'autorisent.
- Garde `BOT_DELAI_ACTIONS` à 1 s ou plus : un bot trop rapide se fait bloquer.
- Ne commite jamais `.env`. Si un mot de passe a fuité, change-le.
