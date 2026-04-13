# Contributing

Thanks for helping improve investigation-agent.

## Setup

```bash
cd investigation-agent
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Copy `config/.env.example` to `config/.env` and configure Telegram (and any other) settings when running integration features; many tests are offline and do not require live credentials.

## Tests

```bash
pytest
```

Run a single file if needed, for example:

```bash
pytest tests/test_parse_id_list.py -v
```

## Pull requests

- Keep changes focused on one concern when possible.
- Add or update tests for behavior you change.
- Run `pytest` before opening a PR.

By contributing, you agree that your contributions are licensed under the same terms as the project ([MIT License](LICENSE)).
