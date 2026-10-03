# Portfolio Analytics

Stock portfolio tracker: a FastAPI backend (PostgreSQL) and a Streamlit frontend.

```
DATA MODELS: https://dbdiagram.io/d/6a6a96c9067336e1de23782e
```

## Requirements

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 from `.python-version`)
- Docker

Install the dependencies from the `Portfolio-Analytics/` folder:

```bash
uv sync
```

## 1. Database (PostgreSQL in Docker)

Create the container once:

```bash
docker run -d --name stock-platform-postgres \
  -e POSTGRES_USER=stock-platform \
  -e POSTGRES_PASSWORD=<choose-a-password> \
  -e POSTGRES_DB=stock-platform-db \
  -p 127.0.0.1:5434:5432 \
  -v stock_platform_postgres_data:/var/lib/postgresql \
  postgres:18
```

After that, just start it when you work on the project:

```bash
docker start stock-platform-postgres
```

The data lives in the `stock_platform_postgres_data` volume, so it survives restarts of the container.

## 2. Environment file

Create `backend/app/.env` (it is gitignored, never commit it):

```bash
SECRET_KEY=<random-key>
DATABASE_URL=postgresql+psycopg://stock-platform:<password>@127.0.0.1:5434/stock-platform-db
```

Generate a `SECRET_KEY` with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Changing the key logs every user out.

## 3. Migrations (Alembic)

The tables are created by Alembic migrations, not by the app. Run this from `backend/app/db/` the first time, and again after pulling new migrations:

```bash
uv run alembic upgrade head
```

After changing a model in `backend/app/models/models.py`:

```bash
uv run alembic revision --autogenerate -m "describe the change"
# read the new file in alembic/versions/ before applying it
uv run alembic upgrade head
```

## 4. Run the app

Backend, from the `backend/` folder:

```bash
uv run fastapi dev app/main.py
```

Frontend, from the `frontend/` folder (in a second terminal):

```bash
uv run streamlit run app.py
```

## Tests

From `Portfolio-Analytics/`:

```bash
uv run pytest
```

The tests use an in-memory SQLite database, so they need neither Docker nor the `.env` file.
