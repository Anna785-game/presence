# Système de sécurité et pointage — API FastAPI + Supabase

Portage du backend Symfony vers FastAPI, avec Supabase comme base Postgres managée + Auth.

## 1. Créer le projet Supabase

1. Va sur https://supabase.com, crée un projet.
2. Dans **SQL Editor**, exécute le contenu de `supabase_schema.sql`.
3. Dans **Authentication > Providers**, active *Email* (ou autre) pour la connexion.
4. Récupère dans **Project Settings > API** : `SUPABASE_URL`, `anon key`, `service_role key`, et le `JWT Secret` (onglet JWT Settings).
5. Récupère la chaîne de connexion Postgres dans **Project Settings > Database**.

## 2. Configurer le backend

```bash
cp .env.example .env
# remplis .env avec tes valeurs Supabase
pip install -r requirements.txt
```

## 3. Lancer en local

```bash
uvicorn app.main:app --reload
```

Documentation interactive auto-générée : http://localhost:8000/docs

## 4. Créer un utilisateur / se connecter

L'auth n'est plus gérée par ce backend (fini `RegistrationController` / `SecurityController` / hashing maison) :
côté frontend, utilise le SDK `supabase-js` (ou `supabase-py`) pour l'inscription/connexion :

```js
const { data, error } = await supabase.auth.signInWithPassword({ email, password })
// data.session.access_token -> à envoyer dans le header Authorization: Bearer <token>
// des futures requêtes vers l'API FastAPI
```

Pour donner le rôle admin à un utilisateur : dans Supabase > Authentication > Users > sélectionner
l'utilisateur > **User Metadata**, ajouter `{"role": "admin"}`.

## 5. Correspondance avec l'ancien projet Symfony

| Symfony                              | FastAPI + Supabase                                    |
|---------------------------------------|---------------------------------------------------------|
| `src/Entity/*.php` (Doctrine)         | `app/db/models.py` (SQLAlchemy)                         |
| `src/Form/*Type.php`                  | `app/schemas/schemas.py` (Pydantic)                      |
| `src/Controller/*Controller.php`      | `app/routers/*.py`                                       |
| `src/Repository/*.php`                | requêtes SQLAlchemy directement dans les routers/services|
| `src/Entity/User.php` + Security      | Supabase Auth (`auth.users`) + `app/core/security.py`    |
| `config/packages/security.yaml`       | `Depends(get_current_user)` / `Depends(require_admin)`   |
| Migrations Doctrine                   | `supabase_schema.sql` (ou Alembic si tu veux versionner) |
| `CalculDureeTravailCommand`           | `POST /jobs/calcul-duree-travail` (à planifier via cron) |
| `InsertAbsenceCommand`                | `POST /jobs/insert-absences` (à planifier via cron)      |
| `ApiPresenceController` (badge RFID)  | `POST /api/entree` (`app/routers/pointage.py`)           |
| Templates Twig                        | À reconstruire côté frontend (React/Vue) qui consomme cette API |

## 6. Ce qu'il te reste à faire

- **Frontend** : les 60+ templates Twig CRUD n'ont pas d'équivalent ici — il te faut un frontend
  (React/Next.js, Vue...) qui appelle ces endpoints.
- **Scheduler** : brancher `pg_cron` (extension Supabase) ou un scheduler externe (GitHub Actions
  cron, Railway cron...) pour appeler `/jobs/calcul-duree-travail` et `/jobs/insert-absences`
  chaque jour, comme le faisaient tes deux `.bat` + Commands Symfony.
- **Sécuriser `/api/entree`** : c'est le boîtier RFID qui appelle cet endpoint, pas un utilisateur
  connecté. Ajoute une clé API dédiée (header `X-Device-Key`) plutôt que de le laisser ouvert.
- **Alembic** (optionnel) : si tu veux versionner tes migrations comme avec Doctrine plutôt que
  gérer le SQL à la main, initialise Alembic avec `DATABASE_URL` pointant sur Supabase.
- **Déploiement** : Railway, Render, Fly.io ou un simple VPS + Docker fonctionnent bien avec ce
  genre de service FastAPI stateless.
