"""The example website's references module: admin screens, the consent rule, images, order and public output."""

from datetime import date, timedelta

import pytest
from flask import render_template_string
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from conftest import csrf_token
from evrima import media
from evrima.auth.models import AuditEntry
from evrima.db import db
from evrima.media.models import MediaFile
from minimal_site.modules import references
from minimal_site.modules.references import Reference
from test_media import as_upload, image_bytes

LIST = "/admin/references/"


@pytest.fixture
def app(make_app):
    """A testing app with the references module enabled."""
    return make_app(modules=[references])


def post(client, path, **data):
    """POST a form of the references admin with a valid CSRF token."""
    return client.post(path, data={"csrf_token": csrf_token(client, LIST), **data})


def add(app, **fields):
    """Store a reference directly and return its id."""
    with app.app_context():
        reference = Reference(client_name=fields.pop("client_name", "Truhlářství Novák"), **fields)
        db.session.add(reference)
        db.session.commit()
        return reference.id


def upload_image(app):
    """An uploaded, not yet claimed image (as the upload field leaves it); returns its id."""
    with app.app_context():
        return media.save_upload(as_upload(image_bytes(), "photo.jpg")).id


def get(app, reference_id):
    """Load a reference in a fresh context."""
    with app.app_context():
        return db.session.get(Reference, reference_id)


def actions(app):
    """Audit actions recorded so far."""
    with app.app_context():
        return [entry.action for entry in db.session.scalars(select(AuditEntry).order_by(AuditEntry.id))]


def test_admin_pages_require_login(client):
    for path in (LIST, LIST + "new"):
        response = client.get(path)
        assert response.status_code == 302 and "/admin/login" in response.headers["Location"]


def test_empty_list(admin_client):
    page = admin_client.get(LIST).get_data(as_text=True)
    assert "Zatím tu není žádná reference." in page


def test_create_a_reference(app, admin_client):
    response = post(admin_client, LIST + "new", client_name="  Pekárna Zrno ", website_url="pekarna-zrno.cz",
                    description='<p>Nový web <script>alert(1)</script><strong>s e-shopem</strong></p>',
                    consent_on="2026-10-01", consent_proof="e-mail z 1. 10. 2026", published="on")
    assert response.status_code == 302
    with app.app_context():
        reference = db.session.scalars(select(Reference)).one()
        assert reference.client_name == "Pekárna Zrno"
        assert reference.website_url == "https://pekarna-zrno.cz"
        assert reference.description == "<p>Nový web <strong>s e-shopem</strong></p>"
        assert reference.consent_on == date(2026, 10, 1)
        assert reference.published is True
    assert "reference.created" in actions(app)
    assert "Pekárna Zrno" in admin_client.get(LIST).get_data(as_text=True)


def test_new_references_start_at_the_top(app, admin_client):
    first = add(app, position=0)
    post(admin_client, LIST + "new", client_name="Newer")
    with app.app_context():
        newest = db.session.scalar(select(Reference).where(Reference.client_name == "Newer"))
        assert newest.position < db.session.get(Reference, first).position


@pytest.mark.parametrize(("data", "message"), [
    ({"client_name": ""}, "Vyplňte název klienta."),
    ({"client_name": "A", "website_url": "not a url"}, "Zadejte platnou adresu webu"),
    ({"client_name": "A", "published": "on"}, "Bez data souhlasu nelze referenci zveřejnit."),
    ({"client_name": "A", "consent_on": "yesterday"}, "Zadejte platné datum."),
    ({"client_name": "A", "consent_on": (date.today() + timedelta(days=5)).isoformat()},
     "nemůže být v budoucnosti"),
], ids=["no-name", "bad-url", "published-without-consent", "bad-date", "future-date"])
def test_invalid_forms_are_shown_again_with_the_problem(app, admin_client, data, message):
    response = post(admin_client, LIST + "new", **data)
    assert response.status_code == 422
    page = response.get_data(as_text=True)
    assert message in page
    assert 'aria-invalid="true"' in page
    with app.app_context():
        assert db.session.scalars(select(Reference)).all() == []


def test_the_database_refuses_publishing_without_consent(app):
    with app.app_context():
        db.session.add(Reference(client_name="Sneaky", published=True))
        with pytest.raises(IntegrityError):
            db.session.commit()


def test_edit_keeps_values_and_rejects_bad_input(app, admin_client):
    reference_id = add(app, consent_on=date(2026, 9, 1), published=True)
    page = admin_client.get(f"{LIST}{reference_id}").get_data(as_text=True)
    assert 'value="Truhlářství Novák"' in page and 'value="2026-09-01"' in page

    response = post(admin_client, f"{LIST}{reference_id}", client_name="Truhlářství Novák", published="on")
    assert response.status_code == 422          # consent date removed while published
    assert get(app, reference_id).consent_on == date(2026, 9, 1)

    response = post(admin_client, f"{LIST}{reference_id}", client_name="Novák a syn")
    assert response.status_code == 302
    edited = get(app, reference_id)
    assert (edited.client_name, edited.published, edited.consent_on) == ("Novák a syn", False, None)
    assert "reference.edited" in actions(app)


def test_missing_reference_is_404(admin_client):
    assert admin_client.get(f"{LIST}999").status_code == 404


def test_image_is_claimed_replaced_and_removed(app, admin_client):
    first = upload_image(app)
    post(admin_client, LIST + "new", client_name="Photo studio", image=str(first))
    with app.app_context():
        reference = db.session.scalars(select(Reference)).one()
        reference_id, first_name = reference.id, reference.image.stored_name
        assert reference.image_id == first and reference.image.claimed_at is not None
    assert "/media/" + first_name in admin_client.get(f"{LIST}{reference_id}").get_data(as_text=True)

    second = upload_image(app)
    post(admin_client, f"{LIST}{reference_id}", client_name="Photo studio", image=str(second))
    with app.app_context():
        assert db.session.get(MediaFile, first) is None
        assert not list(media.media_root().glob(first_name + "*"))
        assert db.session.get(Reference, reference_id).image_id == second

    post(admin_client, f"{LIST}{reference_id}", client_name="Photo studio")      # image removed
    with app.app_context():
        assert db.session.get(Reference, reference_id).image_id is None
        assert db.session.get(MediaFile, second) is None


def test_only_fresh_uploads_can_become_the_image(app, admin_client):
    """A crafted id must not attach (and later delete) another module's file."""
    used = upload_image(app)
    with app.app_context():
        media.claim([used])
    for image in (str(used), "424242", "abc", "²", "9" * 30):
        response = post(admin_client, LIST + "new", client_name="A", image=image)
        assert response.status_code == 422, image
        assert "Obrázek se nepodařilo použít." in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(MediaFile, used) is not None


def test_delete_removes_the_reference_and_its_image(app, admin_client):
    image = upload_image(app)
    post(admin_client, LIST + "new", client_name="Gone", image=str(image))
    with app.app_context():
        reference_id = db.session.scalars(select(Reference)).one().id
    response = post(admin_client, f"{LIST}{reference_id}/delete")
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Reference, reference_id) is None
        assert db.session.get(MediaFile, image) is None
        assert list(media.media_root().iterdir()) == []
    assert "reference.deleted" in actions(app)


def test_order_is_saved(app, admin_client):
    a, b, c = (add(app, client_name=name, position=i) for i, name in enumerate("ABC"))
    post(admin_client, LIST + "order", order=f"{c},{a},{b},999")
    with app.app_context():
        names = [r.client_name for r in db.session.scalars(select(Reference).order_by(Reference.position))]
    assert names == ["C", "A", "B"]
    assert "reference.reordered" in actions(app)


def test_crafted_order_values_are_ignored(app, admin_client):
    """Values such as "²" pass str.isdigit() but not int(); they must not cause an error 500."""
    add(app, client_name="A")
    response = post(admin_client, LIST + "order", order="²,9999999999999999999999,-1,x")
    assert response.status_code == 302


def test_published_lists_only_published_references_in_order(app):
    add(app, client_name="Second", position=2, published=True, consent_on=date(2026, 1, 1))
    add(app, client_name="Hidden", position=0)
    add(app, client_name="First", position=1, published=True, consent_on=date(2026, 1, 1))
    with app.app_context():
        assert [r.client_name for r in references.published()] == ["First", "Second"]


def test_default_public_markup(app):
    image = upload_image(app)
    add(app, client_name="Kavárna", website_url="https://kavarna.example", image_id=image,
        description='<p onclick="x()">Web <script>x()</script>a menu</p>', published=True,
        consent_on=date(2026, 1, 1))
    with app.test_request_context():
        html = render_template_string(
            '{% from "references/_public.html" import reference_list %}'
            '{{ reference_list(published_references(), heading="h2") }}')
    assert '<h2 class="references__name"><a href="https://kavarna.example">Kavárna</a></h2>' in html
    assert "<p>Web a menu</p>" in html
    assert 'type="image/avif"' in html and "-480.avif 480w" in html
    assert 'alt="Kavárna"' in html and 'width="1200" height="800"' in html


def test_the_example_website_shows_references(monkeypatch, tmp_path):
    from conftest import BASE_ENV, https_client
    from evrima.db import migrations

    for key, value in {**BASE_ENV, "MEDIA_ROOT": str(tmp_path / "media")}.items():
        monkeypatch.setenv(key, value)
    from minimal_site import create_app
    site = create_app()
    with site.app_context():
        migrations.upgrade()
    page = https_client(site).get("/references").get_data(as_text=True)
    assert "No published references yet." in page
