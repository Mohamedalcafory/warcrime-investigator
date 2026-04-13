# Investigation Agent

Collect evidence for a **named target** (e.g. a hospital or school) by:

- Searching configured **Telegram channels** for messages matching the target (not full-channel dumps).
- Running a **keyword web search** and extracting article text.

Everything is stored in **SQLite** with source URLs for manual review.

## Setup

```bash
cd investigation-agent
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp config/.env.example config/.env
# Edit config/.env with TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE, TELEGRAM_CHANNELS
```

Environment files are loaded in order (later overrides earlier): `config/.env`, then `.env` at the project root, then `.env` in the current working directory.

First Telegram login will prompt for a code in the terminal and create `investigation_agent_session.session` in the project directory. To reuse an existing Telethon session from another project (same API ID/hash), copy that `.session` file to `investigation_agent_session.session` here.

## Usage

```bash
# Fetch Telegram + web for a target (default: both)
investigate fetch "Al Shifa Hospital"

# Arabic target, web only
investigate fetch "مستشفى الشفاء" --lang ar --no-telegram

# List stored evidence (optionally filter by target substring)
investigate list --target "Shifa"

# Search within stored evidence text
investigate search "emergency" --target "Shifa"
```

## Data

By default the database is `./data/investigation.db` (created automatically).

## License

Private / your use case — add a license if you publish the repo.
