# ServiGo v3

Telegram job matching bot for job seekers and employers.

## Features
- Separate seeker/employer menus
- Short registration questions
- Job browsing and favorites
- Two-sided match approval and private Telegram notifications
- VIP/Premium plans and expiry display
- Employer and seeker dashboards
- Admin approval flow
- Channel deep links
- Railway deployment files

## Local run
1. Copy `.env.example` to `.env` and fill values.
2. `pip install -r requirements.txt`
3. `python bot.py`

## Railway
- Add environment variables from `.env.example`.
- Add a persistent Volume mounted at `/data`.
- Set `DATABASE_PATH=/data/servigo.db`.
- Start command is already defined as `python bot.py`.
- Do not run a second polling instance with the same `BOT_TOKEN`; Telegram permits only one active poller.
- Existing v3 SQLite volumes are migrated automatically when new optional columns are introduced.
- Follow the full production checklist in `DEPLOY.md`.

## Tests

```bash
python -m unittest discover -s tests -v
```

Do not commit `.env` or database files.
