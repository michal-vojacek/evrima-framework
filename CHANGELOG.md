# Changelog

Every release states what changed and whether websites need any change. Versioning rules: [docs/framework.md](docs/framework.md).

## Unreleased

- Repository skeleton: `evrima` package layout, `pyproject.toml` with the version taken from Git tags, MIT licence.
- Core: application factory, configuration loading with startup checks, security headers and CSP, CSRF protection, rate limiter, database session handling, health check, default error pages, `flask evrima` commands, minimal example website.
- Admin languages: Czech and English text catalogues (`translations/*.toml`) with plural forms, a language switch, catalogues of websites and modules loaded next to the framework's.
- Admin frame (sidebar, user menu, flash messages) and the `/admin/design` cookbook, taken over from an earlier admin design of the author; jQuery, DataTables and Font Awesome Free vendored.
- Mobile admin: a top bar with a menu button below 900 px.
- Database migrations with Alembic (`flask evrima db …`), one branch each for the framework, the website and modules.
- E-mail over SMTP (`evrima.mail`), with console and memory backends for development and tests.
- Admin login: password and e-mailed PIN, optional TOTP, trusted devices, lockout, server-side sessions, password reset, invitations, account page, management of administrators, audit log, `flask evrima create-admin | set-admin-email | set-admin-password`.
- Admin design audit: contrast fixes (WCAG AA), no page widening on phones, stacked tables on phones; new components: file upload with previews, gallery and list ordering, busy state of submitted forms, character counter, breadcrumbs, pagination, collapsible sections.
- Uploads in the core (`evrima.media`): images (JPEG, PNG, WebP) and PDF documents checked by content, images cleaned of EXIF and saved with WebP and AVIF variants, files served from `/media/`, background upload in the admin with a progress bar and a queue, `flask evrima media cleanup` for files never used (run daily). New settings: `MEDIA_ROOT`; request bodies up to 25 MB.
- Rich-text editor in the core (`evrima.editor`): headings, paragraphs, bold, links and lists, cleaned with `nh3` on save and on output (`rich` template filter).
- Modules: `create_app(..., modules=[...])` enables the website's modules with their own admin screens, menu items, text catalogue and migration branch; `flask evrima db revision --module <name>`. Migrations created by comparing models only touch their own branch's tables.
- No ready-made content modules: each website writes the modules its client needs, following the new guide `docs/modules.md`. The empty packages for contacts, opening hours, gallery and news were removed.
- References module, now a module of the example website (`examples/minimal/minimal_site/modules/references`, table `references_items`) and the pattern for new modules: admin list with ordering, form with the editor, image and the client's consent (publishing needs it), default public markup with AVIF and WebP images.
- Repository moved to GitHub with a fresh history; the website project lives in its own private repository.
- `/admin/design` is no longer in the admin menu; the URL works for logged-in administrators.
- Login hardening: a pending login expires with its challenge (10 minutes) and is cancelled by a password change; at most 5 wrong codes per challenge, TOTP included; at most 5 code e-mails per account and hour; one's own password only on the account page.
- New setting `SITE_HOSTS` (required in production): requests for other hosts are refused, so links in e-mails cannot be steered by a forged `Host`.
- Uploaded images are decoded only by the decoder of their detected format.
- Modules: names are checked, unprotected admin blueprints are refused, `flask evrima db remove-module <name>`, a clear error for migrations of a module that is no longer enabled, generated migrations never drop tables without a model. New helpers `evrima.admin.forms.parse_id()` / `parse_ids()` and `evrima.media.take()`.
- Websites need changes: no (nothing released yet).
