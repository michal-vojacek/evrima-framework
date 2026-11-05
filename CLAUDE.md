# Evrima

Evrima is a lightweight, security-first framework and CMS on top of Flask for simple websites, developed by Michal Vojáček. Every website is a separate lightweight project that uses Evrima as its core. Evrima is open source (MIT); this repository is public (github.com/michal-vojacek/evrima-framework).

## Documentation

- [docs/framework.md](docs/framework.md): architecture and every decision (distribution, versioning, responsibilities, security baseline, admin, login, e-mail, telemetry, repository structure). **The source of truth.**
- [docs/modules.md](docs/modules.md): how to write a module. Read it before writing or changing any module.
- [CHANGELOG.md](CHANGELOG.md): what changed in each release and whether websites need changes.

## Public repository

- Everything pushed here is public. Never commit secrets, client data, business information or names of private projects.
- The framework ships no content modules. Modules are written in each website's project; `examples/minimal` holds the example module (references) that new modules copy.

## Language

- **All files are in English:** code, identifiers, comments, docstrings, documentation, commit messages.
- Conversation with Michal stays in Czech (global instructions).
- Admin texts are never hard-coded: templates call `t("key")` / `tn("key", count)`, JavaScript reads texts handed over by the page, and every key lives in a `translations/*.toml` catalogue with all languages (Czech and English). Modules ship their own catalogues. See docs/framework.md, "Admin languages".

## Code style

- Code is reasonably commented. Every module, class and function has a docstring saying what it does and, where it is not obvious, why it exists or why it works the way it does.
- Inline comments explain *why* (a decision, a constraint, a trap that was avoided), not what the next line obviously does.
- Match the style of the surrounding code.
- Python `>=3.13`. Dependencies are pinned to exact versions, transitive ones included (`pip freeze`).
- Templates must work under the strict CSP: no inline `<script>`, no `style="…"` attributes, no inline event handlers (`onclick=…`).
- Admin UI is composed from the components on `/admin/design`. A new UI element goes there first, then into the admin.

## Workflow

- Record every decision in [docs/framework.md](docs/framework.md) in the same step, with its date.
- Before a larger change or a new module, propose the approach and wait for approval.
- Do not invent facts. Mark anything unverified as such. Legal and tax information is indicative only, with a recommendation to verify it with a professional.
- Security measures should match realistic risks. For each measure, name the concrete scenario it prevents; prefer simple measures.
- Run the tests before committing: `.venv\Scripts\python -m pytest`.

## Commands

```
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -e .[test]
.venv\Scripts\python -m pytest
.venv\Scripts\flask --app examples/minimal/minimal_site evrima db upgrade
.venv\Scripts\flask --app examples/minimal/minimal_site evrima create-admin you@example.com
.venv\Scripts\flask --app examples/minimal/minimal_site evrima media cleanup
.venv\Scripts\flask --app examples/minimal/minimal_site evrima db revision -m "what changed" --module references
.venv\Scripts\flask --app examples/minimal/minimal_site run --port 5050 --reload
```

The dev server reads `.env` in the repository root (not committed): use a file database (`DATABASE_URL=sqlite:///dev.sqlite3`), because an in-memory SQLite database is not shared between the server's threads. The login PIN is printed to the server's console. Uploaded files land in the app's `instance/media/` folder (git-ignored); `media cleanup` deletes those never used by a saved form and runs daily in production.
