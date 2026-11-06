# Evrima framework

Evrima is the shared foundation (framework and CMS) behind weby-vojacek.cz and all client websites built by Michal Vojáček. The name is internal; client websites do not show it.

**Purpose (decided 2026-10-14):** Evrima is for simple websites. APIs, MCP servers and other custom applications do not belong in the framework. They are usually written as separate applications without Evrima. If something more complex is ever built on top of Evrima, it is added by hand in that project.

Status: architecture decided, implementation in progress. Decided items carry a date; anything else is a proposal awaiting confirmation.

## Principles

- Evrima lives in its own Git repository and is developed as a **Python package** (decided 2026-10-14). The repository is on GitHub, `github.com/michal-vojacek/evrima-framework` (decided 2026-11-05: one account for all of the author's projects).
- **Evrima is open source under the MIT licence** (decided 2026-10-14): anyone may use it for anything, copy it and redistribute it. The only condition is keeping the copyright and licence notice in copies.
- **The Evrima repository is public** (decided 2026-10-14; public since 2026-11-05), so that a client who does not want Michal's hosting, or another supplier, can build the website. Such a client usually receives a finished build that already contains Evrima. The weby-vojacek.cz repository (with business documents) stays private.
- The public repository must never contain secrets or internal information. A security fix is publicly visible once pushed, so it is deployed straight away.
- Every website (weby-vojacek.cz included) is a separate lightweight project that uses Evrima as its core.

## Distribution and deployment (decided 2026-10-14)

- The Evrima version of a website is a setting of its deploy, `EVRIMA_VERSION` (e.g. `1.25.0`).
- A deploy never fetches the "latest" version. Updating the framework is a deliberate change of that setting and a redeploy; whether and when a given website is updated is Michal's call. Release procedure: Michal creates a new version (tag) on GitHub, then changes the setting of the websites to update.
- Dependencies of Evrima and of client applications are pinned to exact versions (`flask==…`), transitive ones included; the list is produced with `pip freeze`. Package hashes are not used (decided 2026-10-14).
- Migrations run once, before the new version starts. If they fail, the new version does not start (decided 2026-10-14).
- Every telemetry batch carries the running Evrima version, so the collector (not built yet) can list websites left on an old release.

**Deploy on DWM (decided 2026-11-05):** websites run on DWM, the author's Docker Compose manager. DWM clones the website's repository, runs its `docker-compose.yml` with the stack's settings and routes domains through Caddy (TLS). The website's compose file and Dockerfile carry the framework version:
- The stack has build enabled; every deploy runs `docker compose up --build`. The Dockerfile's build stage installs `evrima @ git+https://github.com/michal-vojacek/evrima-framework.git@v${EVRIMA_VERSION}`, with `EVRIMA_VERSION` from the stack's settings (passed as a build argument).
- Services: `web` (gunicorn gthread on port 5000, health check on `/health`), `migrate` (`flask evrima db upgrade`, once; `web` starts only after it succeeded), `jobs` (`flask evrima jobs`, since DWM has no cron: telemetry shipping every minute, cleanup of unused uploads and old login records daily), `db` (PostgreSQL) and `redis`, named volumes for data and uploads. Settings reach the containers only through the compose file's `environment`. The app containers run without Linux capabilities and with `no-new-privileges`.
- Reference files and the guide: the website template, `evrima-framework-app-template` (`Dockerfile`, `docker-compose.yml`, `docs/deploy.md`). Checked on 2026-11-05 by building and starting the stack locally (healthy web, migrations, jobs) and by installing the framework from GitHub in the build stage.

## Versioning rules (decided 2026-10-14)

Evrima follows semantic versioning ([semver.org](https://semver.org/)): `MAJOR.MINOR.PATCH`.

| Part | Bumped when | Impact on client websites |
|---|---|---|
| `PATCH` (1.25.**1**) | Bug fixes and security fixes only. No new features, no interface changes. | Can be deployed without touching the website. Typically rolled out to all clients at once. |
| `MINOR` (1.**26**.0) | New features that break nothing. Existing interfaces keep working. | Can be deployed without touching the website. A website uses the new feature once it opts in. |
| `MAJOR` (**2**.0.0) | Any incompatible change: removed or renamed interface, changed behaviour, a migration that changes or deletes data. | The website has to be adapted and tested before deployment. |

Binding rules:

- **A released version is immutable.** A tag is never moved or deleted. A bug in a released version is fixed by a new version.
- A release is a Git tag of the form `v1.25.0`. `.env` always holds an exact version, never a range (`1.25.0`, not `1.25` or `>=1.25`).
- When unsure whether a change is compatible, the higher level applies.
- Bumping `MAJOR` resets `MINOR` and `PATCH`; bumping `MINOR` resets `PATCH`.
- Database migrations in `PATCH` and `MINOR` may only add (new tables, new nullable columns). Anything that changes or deletes existing data or columns belongs to `MAJOR`.
- New columns are always nullable or have a database default. The previous code version therefore keeps working with the new schema, and a failed deploy can be rolled back.
- The package version is derived from the Git tag automatically, so the two cannot drift apart.
- Every release has an entry in `CHANGELOG.md`: what changed and whether websites need any change.
- Release tags are **protected** (on GitHub: a tag ruleset forbidding updates and deletion of `v*` tags), so a released version cannot be moved to other code or deleted (decided 2026-10-14; GitHub since 2026-11-05, the ruleset still to be set up). Tag signatures are not verified.
- Versions `0.x.y` cover development before the first production deployment; during that time incompatible changes may also appear in `MINOR`. The first production version `1.0.0` is released together with the launch of weby-vojacek.cz.

## Responsibilities

| Evrima (framework) | Client application |
|---|---|
| Building the Flask app, configuration from `.env`, configuration check at startup (the app refuses to start without `SECRET_KEY`) | Route declarations |
| Registering the application's routes and blueprints | Templates and static files |
| Security headers, CSP without inline scripts, CSRF | Forms (fields, validation) |
| Rate limiting on Redis, limits configurable per form | Limits of its own forms |
| Form validation, spam protection (honeypot) | Database models |
| Shared minimal rich-text editor, sanitising with `nh3` | |
| PostgreSQL through SQLAlchemy | Its own libraries and logic |
| Migrations (Alembic): a framework branch and an application branch | Migrations of its own models |
| Admin frame: login, menu, look, audit log, image upload | Modules with their own admin screens |
| Administrator management, creating the first administrator by command | |
| The module mechanism and the guide to writing modules ([modules.md](modules.md)) | All content modules (references, price list, gallery…), written for the client |
| Processing uploaded images: size and type limits (no SVG), AVIF and WebP variants in several widths, EXIF removal | |
| `sitemap.xml`, `robots.txt`, `/.well-known/security.txt`, schema.org structured data | Website-specific content |
| Skeleton of legal pages: privacy policy and a cookies page with the framework's own cookies (decided 2026-11-06) | The client's details, the business identification, purposes, processors, retention, third-party cookies (in the website's templates) |
| Static files: cache headers, fingerprinted URLs | |
| Sending e-mail over SMTP | |
| Health check, telemetry including error logging (website side) | |
| Consent banner (cookies), switched on per website: the groundwork only, i.e. storing the visitor's choice per category, the banner and settings templates with texts, the URL, a small script and the controls (decided 2026-11-06) | Whether the website needs it; its categories and which service needs which consent (e.g. how Google Analytics is set up), i.e. what the website does with the choice |
| Default templates (error pages, admin) | May override default templates, except admin templates |

Added after the audit (decided 2026-10-14):
- Admin templates are not overridden in client projects. Changes to the admin belong in the framework.
- The rich-text editor supports only headings, bold, links and lists. Inline styles (colour, font, alignment) are stripped on save.
- CSP: inline scripts are forbidden, `script-src 'self'` is enough. A nonce is used only where inline code cannot be avoided.

The framework ships no content modules (decided 2026-11-05, see "No ready-made modules"). The consent banner is part of the framework for the case when a client explicitly wants Google Analytics, a Facebook pixel and the like (decided 2026-10-14). A website without such scripts and without consent-based analytics shows no banner.

## Security baseline

The framework implements the application part of the hosting security policy (kept with the author's hosting documents, not in this repository). Rules the framework enforces or makes the default:

- HTTPS only. TLS terminates at the reverse proxy (Caddy); the framework sends `Strict-Transport-Security` with `includeSubDomains`. HSTS preload only after the whole domain has been checked: removal from the preload list takes months and affects every subdomain.
- `Content-Security-Policy` without `unsafe-inline` (`script-src 'self'`), plus `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` and `frame-ancestors`.
- **No inline styles (`style="…"`) and no inline scripts in production templates**, the admin included; otherwise the strict CSP cannot hold.
- Session cookies with `Secure`, `HttpOnly` and `SameSite`.
- CSRF tokens in every form, public ones included.
- Spam protection without third-party CAPTCHAs: the honeypot and rate limiting (an IPv6 client counts by its /64).
- Request bodies limited per view (64 KB public, 1 MB admin, more only where a view takes files).
- Secrets never in the repository, only in environment variables or secrets.
- Data minimisation: store only data that is needed, and only for as long as needed.
- Admin: login rate limiting, lockout and an audit log (who changed what and when).
- Each application runs in an isolated Docker container as an unprivileged user, without Linux capabilities (the website template's Dockerfile and compose file).

## Stack (decided 2026-10-14)

- Flask, SQLAlchemy, Alembic, WTForms (Flask-WTF), own admin (frame and modules, see below).
- Gunicorn (sync / `gthread` workers). Eventlet is not used (maintenance-only).
- Templates: the application's own templates are looked up first, then the framework's.
- Framework migrations run automatically together with the application's migrations when the version changes.

## Admin (decided 2026-10-14)

- The framework provides the **admin frame**: login, menu, look, audit log, image upload.
- **Every module has its own screens** and plugs itself into the frame (a menu item, its own pages). Every module is written in the website project (decided 2026-11-05, see "No ready-made modules").
- The admin is not generated from configuration. Even simple modules (references, news) are written the same way, so the system stays uniform.
- `/admin/design` documents the admin design system: a cookbook of every component (modals, buttons, headings, tables, forms…) and of how the admin should look. It is the design of the admin, not of client websites. The design is taken over from an earlier admin design of the author (decided 2026-10-14).
- A new UI element goes to `/admin/design` first, then into the admin.
- `/admin/design` is available to logged-in administrators only and is not in the admin menu (decided 2026-11-05): administrators do not need it, but it stays reachable because whoever writes a module, AI included, composes its screens from it (modules.md).
- Colours stay as taken over for now; they will be reviewed later (decided 2026-10-14).
- jQuery and DataTables stay, for long lists such as references or collected enquiries (decided 2026-10-14).
- Icons: the complete Font Awesome Free (all styles, brands included), vendored locally (decided 2026-10-14).
- Forms: short forms in modal dialogs, larger forms on their own page (decided 2026-10-14).

### Admin languages (decided 2026-10-14)

- The admin is multilingual: Czech and English. Each user picks a language with a switch; the choice is stored in the user's account (login loads it into the session, the switch saves it to the account).
- Texts are kept apart from code, in catalogues, and inserted according to the user's language. Templates and code only contain keys.
- Modules use the same mechanism: every module ships its own catalogue, and the framework loads it.
- Public website texts are not part of this: client websites are Czech and their texts belong to the website.

Implementation (2026-10-14, reviewed and kept 2026-11-06): catalogues are TOML files (`translations/*.toml` in the framework, a module or the website package), each key listing all languages side by side, with plural forms where needed (Czech has three: 1, 2–4, 5+). A missing translation falls back to English, then to the key itself. TOML needs no compile step and Python reads it without extra libraries.

## Operations (decided 2026-10-14)

- Every client has its own application container, its own database container and its own Redis container (Redis decided 2026-10-14, for form rate limiting).

## Admin login (decided 2026-10-14, login method 2026-11-06)

- The framework has a single role: **administrator**. Michal's account and the client's accounts have the same permissions.
- **Login is e-mail and password.** There is no second factor, neither TOTP nor passkeys (decided 2026-11-06): the admin holds no personal data of the website's visitors (enquiries go by e-mail, nothing is stored) and taking an account over allows changing the website's content, not the server or other clients' data. Accepted risk: a leaked or reused password is enough to change the content until it is noticed.
- Response to a taken-over admin account: roll the database back from the external backup to before the break-in and change the passwords together with the client. Backups are not part of the framework; the hosting handles them.
- A user is registered with an e-mail address they cannot change themselves.
- Passwords: **at least 12 characters**, no composition rules (digits, symbols); hashed with **Argon2id** (`argon2-cffi`) at the OWASP minimum, m=19 MiB, t=2, p=1 (decided 2026-11-06: a higher memory cost would let a flood of login attempts take half a gigabyte of memory per website on a shared server). A hash made with other parameters is redone at the next login.
- Failed logins are counted in the database. After 10 failed attempts, login is blocked for 40 minutes counted from the last failed attempt. Attempts are counted per combination of e-mail and client (IPv4 address or IPv6 /64), so a stranger cannot deliberately lock out the real account owner. On top of that, at most 30 login attempts a minute per client (rate limiter). Every login and failed login goes to the audit log.
- Sessions are stored server-side, in the database, behind an `HttpOnly`, `Secure`, `SameSite=Lax` cookie limited to `/admin`. They end after **2 hours of inactivity** and **24 hours** at most. A password change ends all sessions; "log out everywhere" ends all but the current one.
- Password reset and invitations go through e-mail, as one-time links (1 hour and 3 days). Whoever controls the client's mailbox can therefore reset the password; this risk is accepted.
- An administrator sets their own password only on the account page, with the current one (decided 2026-11-05). A browser left logged in can invite an administrator or change another administrator's e-mail; accepted (decided 2026-11-06), the answer is the database rollback above.
- Editing administrators (decided 2026-10-14): an administrator can edit another administrator's name, language and e-mail (e.g. a typo) and set a new password for them, or send them a password reset link. Nobody changes their own e-mail; another administrator or `flask evrima set-admin-email` does. Changing an e-mail or setting a password ends that person's sessions; changing an e-mail also cancels their unused links (they went to the old address) and, for someone still invited, sends the invitation again to the corrected address.
- Accepted: the reset form answers a little later when the address belongs to an administrator (the e-mail is sent during the request). It reveals only whether an address is an administrator's, which is not enough to log in.
- The session cookie serves security only, so it should count as strictly necessary (indicative, to be verified with a lawyer).

## Sending e-mail (decided 2026-10-14)

- E-mails (password reset, invitations, enquiries from forms) are sent over the SMTP of an external service, e.g. Seznam Email Profi or Gmail. No own mail server is run.
- SMTP credentials live in `.env`.

## Telemetry (decided 2026-10-14)

- `TELEMETRY_ENDPOINT` in `.env`: empty = off; an address = shipping to the telemetry collector (evrima-telemetry; only its protocol exists, the collector is not built yet).
- Shipping is asynchronous and batched. An outage of the telemetry server must neither slow down nor break the website.
- IP addresses are not stored.
- When data from client websites is sent to Michal's server, Michal is probably a processor under GDPR and needs a data processing agreement with the client (indicative, to be verified with a lawyer).
- Michal arranges the legal assessment of both levels himself.

**Two telemetry levels:**
- **Level 1, default, without analytics cookies:** operational measurement (response time, page loads and the like), clicks on CTAs, phone, e-mail, WhatsApp and similar links, and submitted enquiries. Clicks are actions on the website, not cookies (decided 2026-10-14).
- **Level 2, with consent (decided 2026-11-06):** recognising unique and returning visitors by a first-party cookie, only after consent through the consent banner. The website switches it on with `TELEMETRY_VISITORS`, naming the consent category it depends on (e.g. `analytics`). Once the visitor allows that category, the script stores 16 random bytes in the `evrima_vid` cookie for 13 months (set once, not extended); the beacon adds it to page views and clicks as `vid` only after checking the consent in the request's own consent cookie, and withdrawing the consent deletes the cookie. The identifier is personal data (an online identifier), so the website's privacy policy must mention it; the skeleton does so on its own. The collector's side is in the protocol (evrima-telemetry, `docs/protocol.md`).
- Clicks are measured by a small own script (event listeners), because `tel:` and `mailto:` links and links to other websites never reach the server.

Principles taken over from an earlier telemetry project of the author:
- Instrumentation never raises. A lost metric is invisible; an exception in a request handler is an outage.
- Request handling makes no network call for telemetry, only an in-memory write. Shipping happens in the background.
- Metric labels have a bounded set of values (the endpoint name, not the full URL; the status class, with the exact code only for failures).
- Static files are not measured.
- Response times are shipped as samples, not as computed percentiles (a percentile cannot be built from other percentiles).
- Every batch carries the running versions.

**Data path and retention (decided 2026-10-14):**
- The application writes telemetry to its Redis. From there it is shipped every minute to `TELEMETRY_ENDPOINT`. Redis acts as a buffer: data survives an application restart and a short outage of the collector.
- Collector side (not built yet): the central database downsamples progressively: the older the data, the coarser the time bucket. The last week in full detail matters most; older data only needs summaries per bucket.
- After a week, individual records (specific errors, slow requests, logs) are dropped. Only summaries remain (e.g. errors per hour).
- A bucket summary stores count, sum, minimum and maximum, and for response times also the basis for percentiles (e.g. TimescaleDB `uddsketch`). An average is computed as sum / count, never as an average of averages, so it is correct at every level.
- Summaries are filled by an own worker, not by automatic database aggregates (they proved hard to control in an earlier project of the author).

Downsampling levels (decided 2026-10-14):

| Resolution | Retention | Purpose |
|---|---|---|
| 5 minutes | 7 days | troubleshooting, full detail including individual errors |
| 1 hour | 3 months | trends over the last quarter |
| 1 day | unlimited | long-term overview, monthly reports for clients |

## Repositories (decided 2026-10-14, updated 2026-11-05)

- This repository holds only the framework. Every file is in English.
- The weby-vojacek.cz website has its own private repository (since 2026-11-05) and uses Evrima like any other website.
- This repository started with a **fresh history** containing only the framework files (decided 2026-10-14). The old shared history contains internal business information and is never published.
- The design audit of 2026-10-14 cites the website's business documents, so it stays in the website's repository. Its outcomes are recorded here as decisions.

## Implementation status

**Core (2026-10-14):** application factory, configuration with startup checks, security headers and CSP, CSRF, rate limiter, database sessions, Redis client, health check, default error pages, `flask evrima` commands, minimal example website, tests.

**Admin frame, first iteration (2026-10-14):** admin languages (catalogues, plural forms, switch), admin layout, macros for fields, dialogs and page forms, `admin.js` with all texts from the catalogue, and the `/admin/design` cookbook. To review together on `/admin/design`: the colours and the source components that the admin may not need.

**Migrations and e-mail (2026-10-14):** `flask evrima db upgrade | current | revision`. The framework, the website and later modules each keep their own Alembic branch (`evrima`, `website`, module name) in their own folder; one upgrade applies them all. E-mail goes through `evrima.mail.send()` with the backend `smtp` (required in production), `console` (development: the message is printed to the console) or `memory` (tests). Messages are plain text.

**Admin login (2026-10-14):** implemented as decided above, in `evrima.auth`: e-mail and password (Argon2id), lockout per e-mail and client, server-side sessions (2 h idle, 24 h at most), password reset and invitations by one-time links (1 hour and 3 days), the account page (profile, password, log out everywhere) and the management of administrators (invite, resend, remove; nobody removes themselves). Every login-related event goes to the audit log. Commands: `flask evrima create-admin`, `set-admin-email`, `set-admin-password`. E-mails are sent in the recipient's language.

**Design audit (2026-10-14):** measured on a phone (375 px) and a desktop (1366 px) on every admin page.
- Fixed: the administrators page was 509 px wide on a phone (a screen-reader-only label escaped its scroll box and widened the page); long inline code overflowed cards.
- Contrast (WCAG AA): the muted text token was darkened (3.9:1 → 5.5:1 on the page background); the primary button starts at aqua-600 instead of aqua-500 (white text 3.6:1 → 5.1:1); sidebar section labels are more opaque; inactive table rows use muted text instead of transparency. The palette is otherwise unchanged.
- Added to the cookbook: file upload (drop zone, previews, type and size check, "tap to choose" on touch screens), gallery and list ordering (drag with a mouse, arrow buttons on touch screens and keyboards, the first photo is the cover), busy state of submitted forms (no double submits), character counter, breadcrumbs, pagination of server-rendered lists, collapsible sections and tables that stack into cards on a phone.
- The admin's CSP also allows `blob:` images, for previews of photos before upload; public pages keep `img-src 'self'`.
- In development, edited text catalogues reload without a restart, like templates.

**Uploads and the rich-text editor belong to the core (decided 2026-10-15):** any module needs them (a gallery, but also, say, a module for documents in PDF), so they are framework services, built now.

Implementation (2026-10-15, reviewed and kept 2026-11-06):
- `evrima.media` stores uploaded files on the local disk under `MEDIA_ROOT` (default: the app's instance folder `media/`; a Docker volume in production, covered by the hosting backups) and records them in the `evrima_media` table.
- The type is decided by the file's content (magic bytes), never by its name or the browser's claim. Allowed: images JPEG, PNG, WebP; documents PDF. SVG and HTML are refused (they can carry scripts).
- Images are decoded and saved again: this removes EXIF (including GPS position) and anything hidden in the file, and turns photos upright. The longest side is capped at 2560 px; variants in WebP and AVIF are made at 480, 960 and 1600 px, never enlarged (a smaller image gets the widths below its own plus one at its full width). Images over 40 megapixels are refused before they are decoded: a small file can unpack into a bitmap that would exhaust the server's memory. A synthetic 12-megapixel photo took about 1 second to process on a development laptop (2026-10-15).
- PDFs are stored unchanged and served with `X-Content-Type-Options: nosniff`, so a browser never runs one as a web page, and under their original name when a visitor saves them. Their CSP allows framing by the website's own pages (the site's policy forbids framing) and loads nothing else. No `sandbox` directive: it protects nothing here and a PDF viewer might refuse to run under it.
- Files are public under `/media/<random name>`; the names cannot be guessed, but nothing secret belongs there.
- The admin uploads each chosen file at once in the background (`POST /admin/media/upload`), with a progress bar per file; the form then submits only the file ids, and cannot be submitted while an upload is still running. At most two files upload at the same time, the rest wait in a queue: processing an image occupies a server worker, and thirty dropped photos must not stall the public website. A module that saves the form "claims" the files; files never claimed are deleted after 24 hours by `flask evrima media cleanup` (run it daily).
- The editor is a minimal `contenteditable` area with a toolbar: heading (H2), subheading (H3), paragraph, bold, link, bulleted and numbered list; Ctrl+B and Ctrl+K work too. Pasted text arrives without formatting. Without JavaScript the field stays a plain textarea. It relies on the browser's `execCommand`, which is deprecated but still supported by every browser and has no replacement for editing; a dependency-free editor library would be the fallback if browsers ever drop it.
- The server is authoritative: every rich text is cleaned with `nh3` on save (allowed: `p`, `br`, `h2`, `h3`, `strong`, `a` with `http`, `https`, `mailto`, `tel` links, `ul`, `ol`, `li`; links get `rel="noopener noreferrer"`) and again on output with the `rich` template filter.

**Modules (decided 2026-10-15):**
- A module is a package with `module = Module(...)`: its name, its folder, its blueprints, its items in the admin menu and an optional setup hook. The website enables modules explicitly, `create_app(__name__, blueprints=[pages], modules=[references])`. Nothing is discovered automatically: a missing or misspelt module stops the startup instead of silently missing.
- Enabling a module loads its catalogue (`translations/`), adds its migration branch (`migrations/versions/`, branch label = module name), registers its blueprints and adds its items to the "Content" section of the admin menu. The website's own modules work the same way.
- A module's templates live under `templates/<module>/` (decided 2026-11-05).
- The public part: a module provides data functions and default markup; the website declares its own routes and decides where the content appears (see "Responsibilities").
- Each table belongs to one migration branch: framework tables start with `evrima_`, module tables carry `info={"evrima_module": name}` and are named `<module>_<things>` (decided 2026-11-05), every other table is the website's. A migration created by comparing models with the database looks only at its own branch's tables, so a website migration never creates or changes a table of the framework or of an enabled module. Website tables must not start with `evrima_`.
- A generated migration never drops a table that has no model (decided 2026-11-05). The database does not remember which module a table belongs to, so the table of a disabled or deleted module would otherwise look like the website's and be dropped with its data. Dropping a table is written by hand.
- `flask evrima db revision -m "…" --module <name>` creates a migration on a module's branch.

**Module checks and removal (decided 2026-11-05, after the code audit):**
- A module name is a lowercase identifier (`[a-z][a-z0-9_]*`, at most 40 characters) and is not `evrima` or `website`: it is also a migration branch label, a catalogue prefix and a template folder.
- A module blueprint under `/admin` must call `protect()`; otherwise the app refuses to start. Forgetting it would publish the module's admin to everyone.
- Removing a module: while it is still enabled, `flask evrima db remove-module <name>` runs its migrations down and so drops its tables and data; then the website stops enabling it. A module disabled without this leaves its revision in the database, and `db upgrade` stops with a message that says what to do (Alembic alone reports only "Can't locate revision", and the deploy would never start the new version).
- `evrima.admin.forms.parse_id()` / `parse_ids()` read ids sent by the browser. `str.isdigit()` accepts characters such as "²" that `int()` refuses, which turned a crafted request into an error 500.
- `evrima.media.take(file_id, kinds=…)` claims a file chosen in a form in one conditional UPDATE, committed together with the module's record, so two forms cannot take the same file and a saved record never points to a file the cleanup could delete.

**No ready-made modules (decided 2026-11-05):** every client needs something slightly different (one wants references and a price list, another a product gallery and no price list). A generic module fills up with options and exceptions and ends up harder to adapt than a new module written for the client. So the framework ships only the module mechanism, its services (uploads, editor, e-mail, migrations, admin components) and the guide [modules.md](modules.md). Every content module is written in the website project (`<website>/modules/`), for that client.
- The example website has a references module (`examples/minimal/minimal_site/modules/references`, table `references_items`). It shows that a website's module works like a framework one, and it is the pattern new modules are copied from.
- A module moves into the framework only when a third website needs it unchanged. Until then it is copied and adapted. The cost is that a fix in one copy does not reach the others; for small modules that is accepted.
- The business identification (name, company ID, registered address) belongs to the website's templates; there are no global site settings in the admin (decided 2026-11-06: changing them by hand is rare). A business has to publish these details on its website (Czech Civil Code § 435; indicative only, to be verified with a professional).

**References module of the example website (decided 2026-10-15):**
- Fields follow the proposal below: client name, website address (typed without `https://`, it gets it), description (the editor), one image (a preview of the project), the date of the client's consent and how it is documented (free text), published, order.
- A reference is published only with a date of consent. The database enforces it too (a check constraint), so no code path can skip the rule. The date may be at most one day in the future (the server counts in UTC).
- New references start at the top of the list; the order is changed by dragging or with arrows, then saved.
- The image must be a freshly uploaded, unused file or the current image: a crafted id could otherwise attach, and later delete, a file of another module. A replaced or removed image is deleted with its variants; deleting a reference deletes its image. Every change goes to the audit log.
- Website: `references.published()` (or `published_references()` in templates) and the default markup `references/_public.html`, `reference_list(items, heading, sizes)`: a `<picture>` with AVIF and WebP variants. `sizes` must describe the website's layout, otherwise the browser downloads a variant that is too small or too large.

**Honeypot for public forms (implemented 2026-11-05, reviewed and kept 2026-11-06):** `evrima.security.honeypot`. A template puts `{{ honeypot("contact") }}` inside the form; the view calls `honeypot.looks_like_bot(request.form, "contact")`.
- A trap field (`homepage`) inside `<div hidden>`: invisible to people and to screen readers, no inline style needed. A naive bot fills it in.
- A render time stamp signed with `SECRET_KEY`, salted with the form's name. A form sent back sooner than 3 seconds (adjustable per call), with a missing or forged stamp, or with a stamp of another form counts as a bot. A stamp older than 7 days counts as a bot too (decided 2026-11-06), so a bot cannot fetch the form once and reuse its stamp for ever. The limit is long on purpose: a refused person is told nothing, so a form left open in a tab over a weekend must still work.
- A form caught by the honeypot should look accepted and send nothing, so the bot learns nothing. It stops only simple bots; the per-form rate limit and CSRF do the rest. Websites must not use the names `homepage` and `form_stamp` for their own fields.

**Telemetry, website side (implemented 2026-11-05, reviewed and kept 2026-11-06):** `evrima.telemetry`, following the protocol in the evrima-telemetry repository (`docs/protocol.md`, the contract with the collector; change it there first).
- On when `TELEMETRY_ENDPOINT` is set; `TELEMETRY_TOKEN` (the website's token, generated and named in the collector) is then required, and the endpoint must be HTTPS in production, except `localhost` and `127.0.0.1` (the token travels in every batch). The address is parsed, and one with a user name, password, query or fragment is refused.
- Server events: every request (endpoint name, method, status class, server time; not static files, uploads, the health check or the beacon), unhandled errors (exception class only, never the message), and form results recorded by the website (`telemetry.event("form", form="contact", result="sent")`).
- Browser events: `{{ telemetry_script() }}` in the website's layout serves `static/evrima/js/telemetry.js` (nothing when off). It sends page views (path without query, entry visit or not, external referrer host, device class, load times) and clicks on `tel:`, `mailto:`, external links and elements marked `data-track="label"` to `POST /_evrima/t` on the website itself. The beacon checks every event against the protocol and drops anything else; no CSRF token (sendBeacon cannot send one, the beacon only counts), 120 requests a minute per client. Only requests from the website's own pages are counted (`Sec-Fetch-Site: same-origin`, or the website's own `Origin`), and the body is read with a cap of 2 KB.
- A visit is counted without any identifier: a page view whose referrer is not the website itself.
- Events go to the Redis list `evrima:telemetry:events` (at most 100 000; without Redis, in the process). `flask evrima telemetry ship` sends them in gzip batches of 1 000 with the token and the running versions (`versions.evrima`, so the collector can list websites left on an old release), every minute from the website's `jobs` container (or a cron job). A batch is moved atomically to an in-flight list with its id and deleted only after the collector accepted it; a failed batch is sent again with the same id; a Redis lock keeps one shipper at a time; redirects are never followed (they could carry the token elsewhere). A batch the collector calls invalid (400, 413) is dropped and logged. Each periodic job of `flask evrima jobs` runs in its own app context (its own database session), and SIGTERM stops the loop between jobs.
- No cookies, IP addresses, user agents, query strings or form contents are collected at level 1; level 2 adds only the visitor id, with consent (see "Telemetry").

**Static files (implemented 2026-11-05, reviewed and kept 2026-11-06):** `evrima.static_files`. `url_for` of the website's and the framework's static files adds `?v=<hash of the content>`; a request with the current hash is cached for a year (`immutable`), anything else is `no-cache` (revalidated with ETag). A query string instead of renamed files: no build step, no manifest. Fonts are not fingerprinted (stylesheets refer to them by plain relative URLs and a fingerprinted preload would download them twice); they are cached for 30 days and served as `font/woff2`, so a replaced font needs a new file name (decided 2026-11-06). In development the hash follows edits without a restart.

**Search engines (implemented 2026-11-05, reviewed and kept 2026-11-06):** `evrima.seo`. The website configures it with create_app overrides: `SITE_URL` (canonical address; default the first of `SITE_HOSTS`), `SITEMAP` (endpoints of public pages), `ROBOTS_BLOCKED_AGENTS` (crawlers kept out, e.g. AI training crawlers), `SECURITY_CONTACT` and `SECURITY_LANGUAGES`. It serves `/robots.txt` (everything allowed except `/admin/`, the sitemap named), `/sitemap.xml`, `/.well-known/security.txt` (RFC 9116, `Expires` computed half a year ahead on each request, so it never goes stale) and gives templates `canonical_url()` and the `json_ld` filter for schema.org data. A JSON-LD block is data, not a script: Chrome does not block it under the strict CSP (checked 2026-11-05); `<`, `>` and `&` are written as JSON escapes, so a value can neither end the block nor switch the HTML parser into a state where the block does not end (decided 2026-11-06).

**Consent banner (implemented 2026-11-06):** `evrima.consent`. The framework prepares the ground only; what a website does with the choice is its own logic (Michal, 2026-11-06: one service, e.g. Google Analytics with its consent mode, can depend on several categories, so the framework must not tie services to categories).
- On when the website sets `CONSENT_CATEGORIES`, e.g. `["analytics", "marketing"]`; necessary cookies are always allowed and never listed. The framework ships texts for `analytics`, `marketing` and `preferences`; another category needs `consent.category.<name>.name` and `.description` in the website's catalogue, checked at startup.
- The choice is stored in the `evrima_consent` cookie (`v<CONSENT_VERSION>.<categories>`, 12 months, `SameSite=Lax`, readable by the page's script). It is not signed: whoever edits it changes only their own choice. Raising `CONSENT_VERSION` asks everyone again.
- Templates: `{{ consent_head() }}` (stylesheet and script) in `<head>`, `{{ consent_banner() }}` before `</body>`, `consent("analytics")` to decide on the server, `consent_settings_url()` for a footer link (with `data-evrima-consent-open` the script opens the banner in place).
- The banner is a plain form, so it works without JavaScript and under the strict CSP: "Reject all" and "Accept all" side by side and alike, "Settings" (a `<details>` with a checkbox per category, none ticked in advance) and "Save my choice". `POST /_evrima/consent` stores the choice and redirects back, or answers JSON to the script, which then hides the banner and fires the `evrima:consent` event (`event.detail.categories`); `evrimaConsent.has()`, `.categories()` and `.open()` serve the website's scripts. `GET /_evrima/consent` is the settings page in the website's layout.
- No CSRF token on the consent endpoint: the token lives in the session, so showing the banner would set the session cookie for every visitor on every page. Requests from other websites are refused instead (`security.same_origin_request()`, the same check as the telemetry beacon), which prevents a forged "accept all".
- Texts are in the website's language (`SITE_LANGUAGE`); a website changes them by overriding `consent/banner.html` or `consent/settings.html`, and the look through the custom properties in `consent.css`. Whether the wording meets the Czech data protection authority's expectations is indicative, to be verified with a lawyer.

**Legal pages (implemented 2026-11-06):** `evrima.legal`. Skeletons of the privacy policy and the cookies page in Czech and English, switched on by `LEGAL_PAGES` (`["privacy", "cookies"]` for the default addresses `/zasady-ochrany-osobnich-udaju` and `/cookies`, in English `/privacy` and `/cookies`; `{page: address}` for others); `legal_url("privacy")` in templates. They extend the website's layout (`SITE_LAYOUT`, default `base.html`, blocks `title` and `content`).
- A website writes `legal/privacy.html` and `legal/cookies.html` extending the skeleton in its language and fills its blocks. The privacy skeleton marks what only the website knows (controller, purposes and legal bases, recipients, retention, effective date) with visible "fill in" notes; it writes the rights of the data subject, the cookies link and, when telemetry is on, a paragraph on visitor statistics (and on the level 2 identifier) itself.
- The cookies page lists the framework's own cookies from the settings (the session cookie that protects forms, `evrima_admin` for administrators, `evrima_consent` with the banner, `evrima_vid` under its category with telemetry level 2); the website adds its own and third-party cookies in the blocks `necessary_cookies` and `category_cookies` (rendered once per category, macro `cookie_row`).
- The skeletons are indicative only; every website's pages are to be checked by a lawyer before launch.

**Operational safeguards (decided 2026-11-06, after a code review and a security audit):**
- A request for a host outside `SITE_HOSTS` (scanners, or upper case: Caddy matches hosts regardless of case) gets a plain-text 400: the website's error page needs routing, which a refused host never reaches.
- `flask evrima jobs` runs each job in its own app context (its own database session) and stops between jobs on SIGTERM. Daily, besides the media cleanup, it removes login records (`evrima.auth.cleanup`): audit entries of failed logins (they hold the typed e-mail and the IP address) after 30 days, lockout counters once they ran out, expired reset and invitation links a day after expiry, and expired sessions. Entries of administrators' own actions stay.
- Rate limits and the login lockout count an IPv6 client by its /64 (`security.client_key()`), IPv4 by its address: one IPv6 customer usually has a whole /64 and could rotate addresses.
- CSRF stays on public forms too (Michal: what arrives was sent from our own page).

**Mobile layout (decided 2026-10-14):** below 900 px the sidebar becomes a top bar that stays in place while scrolling, with a menu button (hamburger) that opens the navigation and the user block as a drop-down panel. Esc or a click outside closes it. The admin needs JavaScript anyway (dialogs, tables), so the menu relies on it too.

Implementation choices made while building the core (reviewed and kept 2026-11-06):
- The website package is the Flask application (`create_app(__name__, blueprints=[…])`); Evrima adds its templates and static files through a blueprint, so the website's folders win. Framework static files are served under `/_evrima/static/`.
- Error pages are rendered from the first existing template: `errors/<code>.html`, `errors/error.html` (website), `evrima/errors/error.html` (framework fallback, in `SITE_LANGUAGE`).
- The health check is `GET /health`: 200 when the database and Redis respond, 503 otherwise; the response names the failing check but never the error text.
- Plain SQLAlchemy instead of Flask-SQLAlchemy, so the migration branches of the framework, modules and website stay explicit. Engines connect lazily, so a website starts while its database is still booting.
- SQLite and in-process rate limits (`memory://`) are accepted in development and testing; production requires PostgreSQL and Redis.
- Session cookies are `Secure` everywhere except development (the development server runs on plain HTTP).
- CSRF tokens have no time limit; they stay bound to the session. Flask-WTF's default of one hour breaks forms left open for a while.
- When Redis is unreachable, the rate limiter lets requests through instead of failing them (login lockout is counted in the database, not in Redis).
- `TRUSTED_PROXIES` (default 1 in production, for Caddy) controls how many `X-Forwarded-*` hops are trusted; the real client IP matters for rate limits and login lockout.
- `SITE_HOSTS` (required in production, decided 2026-11-05) lists the website's host names; Flask's `TRUSTED_HOSTS` refuses any other `Host` with 400. Links in e-mails are built from the request's host, so without it a forged host could make a real password reset e-mail point to an attacker's domain. `localhost` and `127.0.0.1` stay allowed for health checks.
- Request bodies are limited to 25 MB (`MAX_CONTENT_LENGTH`): the admin uploads one file per request, and the largest allowed file is a 20 MB document (decided 2026-10-15).
- Below that ceiling each view has its own limit (decided 2026-11-06): 64 KB (`BODY_LIMIT`) for public pages and the login, 1 MB (`ADMIN_BODY_LIMIT`) under `/admin/` for long texts from the editor. A view that takes files raises it with `@security.body_limit(bytes)`, e.g. the admin upload (25 MB) or a website form with an attachment (Michal: the size depends on what the client's visitors upload, a document or photos). A few slow 25 MB posts to a contact form would otherwise keep every server thread busy.
- In development, templates reload on every request (`TEMPLATES_AUTO_RELOAD`), without Flask's debug mode and its in-browser debugger.

**Settings (`.env` or the deploy's environment):**
- `EVRIMA_ENV` (`production`, `development`, `testing`), `SECRET_KEY` (at least 32 characters), `DATABASE_URL` (PostgreSQL in production), `REDIS_URL` (Redis in production), `SITE_HOSTS` (required in production), `TRUSTED_PROXIES`, `MEDIA_ROOT`, `ADMIN_DEFAULT_LANGUAGE` (`cs` or `en`).
- E-mail: `MAIL_BACKEND` (`smtp` required in production, `console`, `memory`), `MAIL_SENDER`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY` (`starttls` or `ssl`), `SMTP_USERNAME`, `SMTP_PASSWORD`.
- Telemetry: `TELEMETRY_ENDPOINT`, `TELEMETRY_TOKEN`.
- Set by the website in `create_app(config_overrides=…)`: the search engine settings (see "Search engines"), `SITE_LANGUAGE` (`cs` or `en`, default `cs`: the language of the consent banner, the legal skeletons and the fallback error page), `SITE_LAYOUT`, `CONSENT_CATEGORIES` and `CONSENT_VERSION` (see "Consent banner"), `LEGAL_PAGES` (see "Legal pages"), `TELEMETRY_VISITORS` (telemetry level 2), `BODY_LIMIT` / `ADMIN_BODY_LIMIT`, and `CSP`, extra sources per CSP directive for the rare website that needs them (e.g. a third-party script allowed after consent).
- `flask evrima check-config` checks the settings without starting the website; `flask evrima version` prints the running version.

## Repository structure (decided 2026-10-14)

### Evrima framework

```
evrima/
├── pyproject.toml          package, exact pins (==), version from the Git tag
├── LICENSE                 MIT
├── README.md               what Evrima is, how to start a website
├── CHANGELOG.md            what changed, whether websites need changes
├── src/evrima/
│   ├── app.py              create_app(): builds the Flask app, loads the website's modules
│   ├── config.py           loading .env, startup checks
│   ├── cli.py              `flask evrima` commands: version, check-config, db, media, telemetry, jobs
│   ├── errors.py           default error pages
│   ├── i18n.py             admin languages, catalogues
│   ├── redis_client.py     the shared Redis connection
│   ├── static_files.py     fingerprinted static URLs, cache headers
│   ├── version.py          the running Evrima version
│   ├── health.py           health check
│   ├── security/           headers, CSP, CSRF, rate limiting (Redis), honeypot
│   ├── db/                 SQLAlchemy, Alembic integration
│   ├── auth/               login, server-side sessions, lockout, administrators, audit log, cleanup, admin commands
│   ├── admin/              admin frame: look, menu, dialogs, form helpers
│   ├── modules/            the module mechanism (no content modules, see modules.md)
│   ├── editor/             minimal rich-text editor, sanitising (nh3)
│   ├── media/              uploads (images, PDFs): checks, variants, serving, cleanup
│   ├── mail/               sending over SMTP
│   ├── seo/                sitemap.xml, robots.txt, security.txt, canonical URL, schema.org JSON-LD
│   ├── consent/            consent banner: the visitor's choice, banner, settings page
│   ├── legal/              skeletons of the privacy policy and the cookies page
│   ├── telemetry/          collection, Redis buffering, shipping, beacon for the browser script
│   ├── migrations/         framework migration branch
│   ├── templates/evrima/   error pages, admin, consent banner, legal page skeletons
│   ├── translations/       the framework's catalogues (admin, consent banner)
│   └── static/evrima/      admin CSS and JS, editor, telemetry and consent scripts
├── docker/                 pointer to the website template's Dockerfile and docker-compose.yml
├── examples/minimal/       the smallest possible Evrima website, with the example references module
└── tests/
```

A **module** always has the same layout ([modules.md](modules.md)):

```
modules/references/
├── models.py       database models
├── forms.py        forms
├── admin.py        admin screens (plug into the frame)
├── views.py        public views (if the module has any)
├── __init__.py     `module = Module(...)` and the functions for the website
├── templates/<module>/  admin templates and default public templates
├── translations/   the module's text catalogue
└── migrations/versions/  the module's migration branch
```

### Client website

The layout of a website comes from the website template, `evrima-framework-app-template`:

```
mysite-repository/
├── .env.example        settings: EVRIMA_VERSION, SECRET_KEY, database, Redis, SMTP, SITE_HOSTS, telemetry
├── requirements.txt    only the website's own libraries, pinned (the Dockerfile installs Evrima)
├── Dockerfile          installs Evrima v$EVRIMA_VERSION from GitHub, runs gunicorn on port 5000
├── docker-compose.yml  web, migrate, jobs, db, redis
├── mysite/
│   ├── __init__.py     calls Evrima's create_app() with the website's blueprints, modules and settings
│   ├── pages.py        public pages
│   ├── contact.py      the contact form (honeypot, rate limit, e-mail)
│   ├── modules/        the website's modules, if any (see modules.md)
│   ├── templates/      website templates
│   └── static/         CSS, JS, images, fonts
└── tests/
```

A website with its own models adds its migration branch (`mysite/migrations/versions/`).

### Outside the Evrima repository

- **DWM:** the author's Docker Compose manager that runs the websites. Evrima supplies nothing to it directly; the website template carries the Dockerfile and compose file.
- **Central telemetry collection** (ingest, downsampling worker, database): the evrima-telemetry project; only its protocol exists, the collector is not built yet. A self-hosting client does not need it.

## Example: Reference model (implemented 2026-10-15, see "References module of the example website")

| Field | Type | Note |
|---|---|---|
| client name | text, required | |
| website URL | URL | format validated |
| description | rich text | sanitised with `nh3` |
| image | file | type check, conversion to WebP/AVIF, EXIF removal |
| date of consent | date, optional | published only with a date of consent |
| proof of consent | text | how consent is documented (e-mail, contract); free text, up to 500 characters (decided 2026-10-15) |
| published | yes/no | |
| order | number | |

## Open questions

- None at the moment.

**Error pages for visitors (decided 2026-11-06):** they are always in the language of the website, which decides how to handle them (above all its own 404 page, `errors/404.html`). The framework's fallback page, written in `SITE_LANGUAGE`, only helps until the website has its own.
