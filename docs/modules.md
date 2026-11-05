# Writing a module

Evrima ships no content modules (decided 2026-11-05). Every website writes the modules its client needs, such as references, a price list or a product gallery, in its own project. This guide is written so that a developer, or an AI, can build a module from it alone. The fields and behaviour of a module are decided with the client each time; the way it is built is always the same.

**The pattern to copy** is the references module of the example website, [examples/minimal/minimal_site/modules/references/](../examples/minimal/minimal_site/modules/references/), with its tests in [tests/test_references.py](../tests/test_references.py). When this guide and the pattern disagree, the guide wins; please fix the pattern.

**The look** comes from `/admin/design`: open it in the admin of a running website (it is not in the menu). Every admin screen is composed from the components shown there. A component that is missing goes to `/admin/design` in the framework first.

## 1. Before writing code

Write a short proposal and get it approved. It covers:

- the fields: type, required or not, limits (length, range), default;
- the rules (e.g. "published only with the client's consent") and where each is enforced: form, database, or both;
- the admin screens: a list, and a form **in a dialog** (short forms, up to about six fields) or **on its own page** (long forms, rich text, images);
- ordering (manual drag and drop, or by a field such as a date);
- where and how the content appears on the website;
- personal data, if any: what is stored, why, and for how long.

## 2. Layout

```
<website>/modules/<name>/
├── __init__.py          module = Module(...) and the functions the website calls
├── models.py            database models
├── forms.py             reading and checking submitted values
├── admin.py             admin screens
├── views.py             public routes, only if the module has pages of its own
├── templates/<name>/
│   ├── admin/…          admin pages
│   └── _public.html     default markup for website pages (macros)
├── translations/<name>.toml
└── migrations/versions/ the module's migration branch
```

`<name>` is a lowercase identifier: letters, digits and underscores, starting with a letter, at most 40 characters, not `evrima` or `website` (the app refuses anything else at startup). The same name is the migration branch label, the prefix of every catalogue key (`pricing.title`), the template folder and the start of the blueprint names (`pricing_admin`, `pricing_public`).

## 3. The module description (`__init__.py`)

```python
"""Price list: services and their prices, shown on the website."""

from pathlib import Path

from flask import Flask
from sqlalchemy import select

from evrima.db import db
from evrima.modules import MenuItem, Module
from mysite.modules.pricing.admin import bp as admin_bp
from mysite.modules.pricing.models import PriceItem

__all__ = ["PriceItem", "module", "published"]


def published() -> list[PriceItem]:
    """Published items in the order set in the admin."""
    return list(db.session.scalars(
        select(PriceItem).where(PriceItem.published).order_by(PriceItem.position, PriceItem.id)))


def _setup(app: Flask) -> None:
    """Make the published items available to every website template."""
    app.jinja_env.globals["published_price_items"] = published


module = Module(
    name="pricing",
    root=Path(__file__).resolve().parent,
    blueprints=(admin_bp,),                 # plus the public blueprint, if any
    menu=(MenuItem("pricing_admin.index", "tags", "pricing.nav"),),
    setup=_setup,
)
```

The website enables it explicitly: `create_app(__name__, blueprints=[pages], modules=[references, pricing])`. Nothing is discovered automatically. The menu icon is a Font Awesome solid icon name without `fa-`.

## 4. Models and migrations

```python
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from evrima.db import Base, utcnow


class PriceItem(Base):
    """One service with its price."""

    __tablename__ = "pricing_items"
    __table_args__ = (
        CheckConstraint("price >= 0", name="price_not_negative"),
        {"info": {"evrima_module": "pricing"}},        # always last in the tuple
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
```

- Tables are named `<name>_<things>`. Never `evrima_…`, which is the framework's.
- Every table carries `{"info": {"evrima_module": "<name>"}}`. Migrations use it to tell the module's tables from the website's.
- **Money is `Numeric` and `Decimal`, never `float`.** A float cannot hold 0.1 exactly, and sums drift. Parse with `Decimal(text.replace(",", "."))` and catch `InvalidOperation`. A price shown as free text ("from 5 000 CZK", "by agreement") is a `String`, not a number.
- Dates and times: `datetime` in UTC (`utcnow`); plain dates (`date`) for calendar days.
- A rule that must never be broken goes into the database too (`CheckConstraint`, `nullable=False`, `unique=True`), so no code path can skip it.
- `default=` works only in Python. A column added to a table that already has rows also needs `server_default=` in the migration (see the versioning rules in framework.md).

**The first migration:**

1. Enable the module in the website and run `flask evrima db upgrade` (Alembic compares the models with a migrated database).
2. `flask evrima db revision -m "pricing" --module pricing` writes the first migration into `migrations/versions/` and labels the branch.
3. Read the generated file. A module that refers to a framework table (`ForeignKey("evrima_media.id")` for images) adds the framework revision that created it, `depends_on = '9701535e0597'` (the media table), as in the references module.
4. `flask evrima db upgrade` again.

Later changes: change the model, then `db revision --module <name>` again. A generated migration never drops a table, and once a module is deployed its migrations only add (new tables, nullable columns or columns with a server default).

**Removing a module:** while it is still enabled, `flask evrima db remove-module <name>` drops its tables and data; then stop enabling it and delete its code. A module simply dropped from `create_app` leaves its revision in the database, and `db upgrade` stops with a message saying what to do.

## 5. Reading forms (`forms.py`)

Admin forms are read by hand, without WTForms: the rules read better as plain code, and the errors go next to the fields. A form is a dataclass with the typed values (for showing them again), the parsed values and `errors`, a dict of field name to catalogue key. See `references/forms.py`.

- Trim strings and check their length against the column (`len(value) > 200`).
- Ids sent by the browser (a chosen image, an order): `evrima.admin.forms.parse_id(text)` and `parse_ids("3,1,2")`. Never `int()` on raw input: `"²".isdigit()` is true but `int("²")` raises, which is an error 500.
- Rich text: `evrima.editor.sanitize(html)` on save.
- Web addresses: allow only `http` and `https` (see `valid_url` in the references form).
- Checkboxes: `data.get("published") == "on"`.

## 6. Admin screens (`admin.py`)

```python
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from evrima import media                  # only for uploads (section 7)
from evrima.admin import modal
from evrima.admin.forms import parse_id, parse_ids
from evrima.auth import audit, protect
from evrima.auth.sessions import current_admin
from evrima.db import db
from evrima.i18n import translate as t

bp = Blueprint("pricing_admin", __name__, url_prefix="/admin/pricing", template_folder="templates")
protect(bp)          # without it the app refuses to start
```

Rules for every screen:

- POST, then redirect (a refresh never sends a form twice). Deleting and reordering are POST forms too.
- Every change goes to the audit log: `audit.record("price_item.created", admin=current_admin(), detail=item.name)`. Actions: `created`, `edited`, `deleted`, `reordered`.
- After a successful save: `flash(t("pricing.saved", name=item.name), "success")`.
- A missing record is `abort(404)`.
- All texts come from the catalogue (`t()`, `tn()`), never from Python or the template.

### A short form in a dialog

The list page holds one dialog for adding and editing. "Add" opens it empty; "Edit" opens it filled (`fill=`), including a hidden `id`, so one `save` view creates or updates. `fill` sets field values only, never the form's address. A rejected form redirects back to the list, and the dialog opens again with the typed values and the error (`evrima.admin.modal`).

```python
@bp.post("/save")
def save():
    """Add a price item, or edit the one named by the hidden `id`."""
    back = url_for("pricing_admin.index")
    item_id = parse_id(request.form.get("id"))
    item = db.session.get(PriceItem, item_id) if item_id else PriceItem()
    if item is None:
        abort(404)
    form = PriceItemForm.from_request(request.form)
    if form.errors:
        return modal.reopen("price-item", t(next(iter(form.errors.values()))), back)
    form.apply(item)
    if item_id is None:
        db.session.add(item)
    db.session.commit()
    audit.record("price_item.edited" if item_id else "price_item.created", admin=current_admin(), detail=item.name)
    flash(t("pricing.saved", name=item.name), "success")
    return redirect(back)
```

```jinja
{% from "evrima/admin/_macros.html" import page_header, csrf, field, modal, modal_error, modal_actions, mv, open_button, empty %}
{% call page_header(t("pricing.title"), t("pricing.subtitle"), "tags") %}
  {{ open_button("price-item", t("pricing.add"), fill={}) }}
{% endcall %}
{# in each row of the list: #}
{{ open_button("price-item", t("pricing.edit"), icon="pen", cls="btn--ghost",
               fill={"id": item.id, "name": item.name, "price": item.price | string}, title=t("pricing.edit")) }}

{% call(reopened) modal("price-item", t("pricing.add"), "tags") %}
<form method="post" action="{{ url_for('pricing_admin.save') }}">
  {{ csrf() }}
  <input type="hidden" name="id" value="{{ mv('price-item', 'id') }}">
  <div class="modal__content">
    {{ modal_error("price-item") }}
    {{ field("name", t("pricing.field.name"), mv("price-item", "name"), required=True, prefix="price-item-") }}
    {{ field("price", t("pricing.field.price"), mv("price-item", "price"), attrs={"inputmode": "decimal"}, prefix="price-item-") }}
  </div>
  {{ modal_actions() }}
</form>
{% endcall %}
```

- `open_button(target, label, icon='plus', cls='btn--primary', fill=None, title=None)`: with `fill` (a dict, `{}` for "add") the form is reset and filled first; `title` replaces the dialog's title.
- `mv(dialog, name, default)` puts the submitted value back after a rejected form.
- A page with several forms passes `prefix=` to each field, so labels point at their own fields.

### A long form on its own page

Rich text, images or many fields: a page of its own (`references/admin/form.html`). A rejected form is rendered again directly with status **422** and the errors next to the fields:

```jinja
{% set e = form.errors %}
{{ field("name", t("pricing.field.name"), form.name, required=True,
         invalid=(t(e.name) if "name" in e else None)) }}
{{ editor("description", t("pricing.field.description"), form.description) }}
{{ page_form_actions(url_for("pricing_admin.index")) }}
```

### Components (macros in `evrima/admin/_macros.html`)

| Macro | Use |
|---|---|
| `page_header(title, subtitle, icon)` with `{% call %}` | page title, buttons on the right |
| `field(name, label, value, type, hint, required, placeholder, attrs, readonly, invalid, prefix)` | one-line input; `attrs` adds attributes (escaped) |
| `textarea(name, label, value, rows, hint, required, placeholder, prefix, maxlength)` | plain text; `maxlength` adds a counter |
| `select(name, label, options, value, hint, prefix)` | `options` = `[(value, label)]` |
| `editor(name, label, value, hint, required, prefix, rows)` | rich text (headings, bold, links, lists) |
| `upload(name, label, multiple, accept, max_bytes, hint, prefix, kinds, files)` | images or PDFs, uploaded in the background |
| `modal`, `modal_error`, `modal_actions`, `mv`, `open_button` | dialogs, above |
| `page_form_actions(cancel_url, submit, icon)` | Cancel and Save under a page form |
| `breadcrumbs([(label, url)])`, `pagination(page, pages, url)` | navigation of nested pages and long lists |
| `empty(text, hint)` | an empty list |
| `csrf()` | in every form |

Behaviour comes from `admin.js` through `data-*` attributes. Templates have no inline `<script>`, no `style="…"` and no `onclick=…` (the CSP blocks them):

- **Ordering:** `<ul class="sortable-list" data-sortable data-sortable-input="order">` with items `<li data-sortable-item data-id="…" data-label="…" draggable="true">` and buttons `data-move="up"` / `data-move="down"`. On submit the hidden input `order` holds the ids in the new order, e.g. `"3,1,2"`; read it with `parse_ids`.
- **Delete with confirmation:** a hidden form per item with `data-confirm`, `data-confirm-title` and `data-confirm-ok` texts, submitted by a button with `form="delete-<id>"` (forms cannot be nested).
- Status labels: `<span class="status status--ok | status--na | status--warn">`.

Copy the markup of the references list (`references/admin/list.html`) and the matching component on `/admin/design`.

## 7. Images and documents

1. The form uses `upload("image", t("pricing.field.image"), files=files)`. The browser uploads the file at once and the form sends only its id.
2. On save, read the id with `parse_id`, then claim it **before** the commit:

```python
if form.image_id is not None and form.image_id != item.image_id:
    if media.take(form.image_id, kinds=("image",)) is None:
        form.errors["image"] = "pricing.error.image"     # someone else's file, or not an image
replaced = item.image if item.image_id != form.image_id else None
item.image_id = form.image_id
db.session.commit()                                      # the record and the claim together
if replaced is not None:
    media.delete(replaced)
```

3. Deleting the record deletes its file: `media.delete(item.image)` after the commit.

The model refers to the file with `ForeignKey("evrima_media.id", ondelete="SET NULL")` and `relationship(lazy="joined")`, and the migration has `depends_on` (section 4). Files never claimed are deleted by `flask evrima media cleanup`. In templates: `media_url(file, width)` and `media_srcset(file, "avif" | "webp")` (see `references/_public.html` for a `<picture>`).

## 8. Texts (`translations/<name>.toml`)

```toml
# Texts of the pricing module.

[pricing.nav]
en = "Price list"
cs = "Ceník"

[pricing.saved]
en = "{name} saved."
cs = "Položka {name} je uložená."

[pricing.count]
en = { one = "{count} item", other = "{count} items" }
cs = { one = "{count} položka", few = "{count} položky", other = "{count} položek" }
```

- Every key starts with `<name>.` and has both `en` and `cs`. A key defined twice in the app is an error.
- Placeholders in braces: `t("pricing.saved", name=item.name)`. Plurals: `tn("pricing.count", n)`; Czech has `one` (1), `few` (2–4) and `other`.
- Czech texts use standard Czech, without slang.

## 9. The public part

The module provides data functions (`published()`) and default markup in `templates/<name>/_public.html` as macros. The website decides where the content appears:

```python
@pages.get("/cenik")
def price_list():
    """The price list page."""
    return render_template("price_list.html", items=pricing.published())
```

```jinja
{% from "pricing/_public.html" import price_list %}
{{ price_list(items) }}
```

A module has its own public routes (`views.py`, a blueprint without `protect`, named `<name>_public`) only when it has pages of its own, for example a page per product. Public output is escaped automatically; rich text is printed with `{{ item.description | rich }}`, never `| safe`.

## 10. Tests

Tests live with the website. Copy the fixtures from the framework's [tests/conftest.py](../tests/conftest.py) (the framework does not ship them as a package yet):

- `make_app(modules=[pricing])` builds a migrated testing app;
- `admin_client` is a logged-in HTTPS client;
- `add_admin`, `log_in`, `https_client`, `csrf_token(client, path)` and `last_pin`.

Every module tests at least:

- that the admin requires login (an anonymous request is redirected to `/admin/login`);
- creating, editing, deleting and reordering, with their audit log entries;
- that rejected input comes back with its error (422 for a page, the reopened dialog for a dialog);
- each rule, including the database constraint (inserting directly must raise `IntegrityError`);
- crafted input: a non-numeric or huge id, a foreign file id;
- uploads, if any: claiming, replacing and deleting files;
- the public output;
- that the migration matches the models:

```python
from evrima.db import migrations

def test_the_migration_matches_the_models(make_app):
    with make_app(modules=[pricing]).app_context():
        assert migrations.model_differences("pricing") == []
```

## 11. Checklist

- [ ] The proposal was approved.
- [ ] Name, tables `<name>_…`, `info={"evrima_module": …}`, catalogue keys `<name>.…`.
- [ ] `protect(bp)` on the admin blueprint; POST + redirect; `abort(404)` for missing records.
- [ ] Ids parsed with `parse_id`; files claimed with `media.take` before the commit.
- [ ] Money in `Numeric` / `Decimal`; rules also in the database.
- [ ] Every change in the audit log; every text in the catalogue in Czech and English.
- [ ] Screens built from `/admin/design` components; no inline scripts or styles.
- [ ] Migration generated, read, and `model_differences` is empty.
- [ ] Tests from section 10 pass.

## 12. When a module moves into the framework

A module is copied into a new website and adapted there. It moves into the framework only when a third website needs it unchanged (decided 2026-11-05). Until then, a fix in one copy does not reach the others; for small modules that cost is accepted.
