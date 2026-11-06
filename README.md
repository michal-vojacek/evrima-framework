# Evrima

A lightweight, security-first framework and CMS on top of Flask for simple websites. Every website is a separate lightweight project that uses Evrima as its core: the framework provides security, the database layer, the admin with login, uploads and a rich-text editor, and the module mechanism; the website provides routes, templates, content and its modules, written for its client ([docs/modules.md](docs/modules.md)).

**Status:** in development (version `0.x`), not ready for production use. The telemetry collector is a separate project, not built yet. The first production version `1.0.0` will be released together with the launch of the author's own website.

Architecture and decisions: [docs/framework.md](docs/framework.md).

## Quick look

A website is a Flask package that hands its blueprints to Evrima:

```python
from evrima import create_app

from mysite.modules import pricing, references
from mysite.pages import pages

app = create_app(__name__, blueprints=[pages], modules=[references, pricing])
```

Content (references, a price list, a gallery…) comes from modules written for each website: see [docs/modules.md](docs/modules.md). [examples/minimal](examples/minimal) is a complete, runnable website with one module.

## Development

```
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -e .[test]
.venv\Scripts\python -m pytest
```

## Licence

[MIT](LICENSE)

A new website starts from the template [evrima-framework-app-template](https://github.com/michal-vojacek/evrima-framework-app-template): skeleton, Docker files for deploying on DWM, and a guide.
