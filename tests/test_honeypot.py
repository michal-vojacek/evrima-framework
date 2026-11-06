"""The honeypot of public forms: trap field and signed render time."""

import re

import pytest
from flask import render_template_string
from werkzeug.datastructures import MultiDict

from evrima.security import honeypot


def rendered(app, form="contact"):
    """The honeypot markup as a template renders it."""
    with app.test_request_context():
        return render_template_string("{{ honeypot(form) }}", form=form)


def submitted(html, **fields):
    """Form data as a browser would send it from `html`, plus `fields`."""
    stamp = re.search(rf'name="{honeypot.STAMP_FIELD}" value="([^"]+)"', html).group(1)
    return MultiDict({honeypot.TRAP_FIELD: "", honeypot.STAMP_FIELD: stamp, **fields})


@pytest.fixture
def later(monkeypatch):
    """Move the clock forward by `seconds` after the form was rendered."""
    real_now = honeypot._now

    def move(seconds):
        monkeypatch.setattr(honeypot, "_now", lambda: real_now() + seconds)
    return move


def test_markup_hides_the_trap_without_inline_styles(app):
    html = rendered(app)
    assert f'<div hidden><input type="text" name="{honeypot.TRAP_FIELD}"' in html
    assert 'tabindex="-1"' in html and 'autocomplete="off"' in html
    assert "style=" not in html


def test_a_person_passes(app, later):
    html = rendered(app)
    later(10)
    with app.app_context():
        assert not honeypot.looks_like_bot(submitted(html), "contact")


def test_a_filled_trap_is_a_bot(app, later):
    html = rendered(app)
    later(10)
    with app.app_context():
        assert honeypot.looks_like_bot(submitted(html, homepage="http://spam.example"), "contact")


def test_an_instant_submit_is_a_bot(app):
    html = rendered(app)
    with app.app_context():
        assert honeypot.looks_like_bot(submitted(html), "contact")


def test_the_minimum_time_can_be_set(app, later):
    html = rendered(app)
    later(10)
    with app.app_context():
        assert honeypot.looks_like_bot(submitted(html), "contact", min_seconds=30)


@pytest.mark.parametrize("stamp", ["", "123", "1700000000.forged", "x" * 500])
def test_a_missing_or_forged_stamp_is_a_bot(app, stamp):
    with app.app_context():
        data = MultiDict({honeypot.TRAP_FIELD: "", honeypot.STAMP_FIELD: stamp})
        assert honeypot.looks_like_bot(data, "contact")


def test_a_stamp_from_another_form_is_a_bot(app, later):
    html = rendered(app, form="newsletter")
    later(10)
    with app.app_context():
        assert honeypot.looks_like_bot(submitted(html), "contact")


def test_a_stamp_signed_with_another_key_is_a_bot(make_app, later):
    html = rendered(make_app(SECRET_KEY="another-secret-key-" + "z" * 32))
    later(10)
    with make_app().app_context():
        assert honeypot.looks_like_bot(submitted(html), "contact")


def test_an_old_stamp_is_a_bot(app, later):
    html = rendered(app)
    later(honeypot.MAX_SECONDS - 60)
    with app.app_context():
        assert not honeypot.looks_like_bot(submitted(html), "contact")
    later(honeypot.MAX_SECONDS + 60)
    with app.app_context():
        assert honeypot.looks_like_bot(submitted(html), "contact")
