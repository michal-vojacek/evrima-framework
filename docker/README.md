# Docker

The Dockerfile and `docker-compose.yml` of a website live in the website's own repository; the reference versions are in the website template, [evrima-framework-app-template](https://github.com/michal-vojacek/evrima-framework-app-template) (`Dockerfile`, `docker-compose.yml`, `docs/deploy.md`). A new website starts from there.

What the framework provides for them:

| Command | Used by |
|---|---|
| `flask evrima db upgrade` | the one-shot `migrate` service, before the website starts |
| `flask evrima jobs` | the `jobs` service: telemetry shipping every minute, cleanup of unused uploads and old login records daily |
| `GET /health` | the health check of the `web` service (200 when the database and Redis respond) |
| `flask evrima check-config` | checking the settings inside a container |

The image installs an exact framework release from GitHub (`v$EVRIMA_VERSION`) at build time; see docs/framework.md, "Distribution and deployment".
