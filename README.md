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

# Semantic search (ChromaDB embeddings; new fetches index automatically)
investigate reindex
investigate semantic-search "hospital fuel generators" --target "مجمع" --limit 10

# Analyst review (pending | approved | rejected)
investigate review list --status pending
investigate review set --ids 58,56 --status approved

# Summarize only approved rows
investigate summarize --target "مجمع" --limit 8 --approved-only
```

ChromaDB files live under `./data/chroma` by default. Override with `CHROMA_PERSIST_DIR` in `config/.env`.

**First run:** The default embedding model (~80MB ONNX) is downloaded once to your Chroma cache (e.g. `~/.cache/chroma/`). The first `reindex` or `semantic-search` after install may take a minute while that completes.

## Local LLM (Ollama)

Install [Ollama](https://ollama.com/) and pull the default model used by this project:

```bash
ollama pull qwen2.5:3b-instruct
```

Configure in `config/.env`:

- `OLLAMA_BASE_URL` (default `http://localhost:11434`)
- `OLLAMA_MODEL` (must match a model you have pulled)
- `OLLAMA_TIMEOUT_SECONDS`

Then:

```bash
# Summarize a batch (asks model for citation-style bullets; always lists batch URLs)
investigate summarize --target "مجمع الشفاء الطبي" --limit 8

investigate summarize --ids 58,56

# Structured extraction per row (JSON stored in DB column classification_json)
investigate extract --target "مجمع الشفاء الطبي" --limit 10

investigate extract --ids 58,55
```

Extraction is analyst aid only — verify against sources.

## Data

By default the database is `./data/investigation.db` (created automatically).

## License

Private / your use case — add a license if you publish the repo.
