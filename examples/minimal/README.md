# Minimal Evrima website

The smallest possible website on Evrima: a home page, a references page and one module (`minimal_site/modules/references`), the pattern for new modules ([docs/modules.md](../../docs/modules.md)). It is used by the framework's tests and shows how a website is put together.

```
cd examples/minimal
copy .env.example .env        (then put a random SECRET_KEY into .env)
..\..\.venv\Scripts\flask --app minimal_site run
```

Generate a secret key with:

```
..\..\.venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Before the first start, create the database tables and the first administrator:

```
..\..\.venv\Scripts\flask --app minimal_site evrima db upgrade
..\..\.venv\Scripts\flask --app minimal_site evrima create-admin you@example.com --name "Your Name"
```

The admin is at `/admin`. In development e-mails (password reset links, invitations) are printed to the server's console instead of being sent.
