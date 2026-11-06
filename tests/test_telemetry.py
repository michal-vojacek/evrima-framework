"""Telemetry: collecting server and browser events, the beacon, shipping to the collector."""

import gzip
import http.server
import io
import json
import threading

import fakeredis
import pytest
import redis
from flask import Blueprint

from conftest import https_client
from evrima import redis_client, telemetry
from evrima.config import ConfigError, load_config
from evrima.telemetry import beacon, ship

ON = {"TELEMETRY_ENDPOINT": "https://collector.example.com/", "TELEMETRY_TOKEN": "site-token"}

probe = Blueprint("telemetry_probe", __name__)


@probe.get("/probe")
def probe_page():
    return "ok"


@probe.get("/probe/fail")
def probe_fail():
    raise RuntimeError("secret personal detail")


@probe.get("/probe/script")
def probe_script():
    from flask import render_template_string
    return render_template_string("{{ telemetry_script() }}")


def buffered(app):
    """The events waiting in the buffer (not those in flight), decoded."""
    with app.app_context():
        client = redis_client.get_client()
        items = client.lrange(telemetry.BUFFER_KEY, 0, -1) if client else app.extensions.get(telemetry._LOCAL_KEY, [])
        return [json.loads(item) for item in items]


def browser(app):
    """A client that sends what a browser sends from the website's own page."""
    client = https_client(app)
    client.environ_base["HTTP_SEC_FETCH_SITE"] = "same-origin"
    return client


def record_numbers(app, numbers):
    with app.test_request_context():
        for number in numbers:
            telemetry.event("form", form=f"f{number}", result="sent")


def record(app, count):
    record_numbers(app, range(count))


@pytest.fixture
def on_app(make_app):
    return make_app(env=ON, blueprints=[probe])


@pytest.fixture(params=["process", "redis"])
def ship_app(request, make_app):
    """An app with telemetry on, buffering in the process or in (fake) Redis."""
    app = make_app(env=ON, blueprints=[probe])
    if request.param == "redis":
        app.extensions[redis_client._EXTENSION_KEY] = fakeredis.FakeRedis()
    return app


def test_off_by_default_nothing_is_collected(make_app):
    app = make_app(blueprints=[probe])
    client = https_client(app)
    client.get("/probe")
    assert buffered(app) == []
    assert client.get("/probe/script").get_data(as_text=True) == ""
    assert client.post("/_evrima/t", data=json.dumps({"t": "pageview", "path": "/"})).status_code == 204
    assert buffered(app) == []


def test_requests_are_measured_by_endpoint_not_url(on_app):
    client = https_client(on_app)
    client.get("/probe?email=someone@example.com")
    client.get("/missing")
    client.get("/health")
    client.get("/_evrima/static/js/telemetry.js")
    events = buffered(on_app)
    assert [(e["endpoint"], e["status"]) for e in events] == [("telemetry_probe.probe_page", "2xx"), ("(none)", "404")]
    assert all(e["t"] == "request" and e["method"] == "GET" and e["ms"] >= 0 and e["at"].endswith("Z") for e in events)
    assert "someone" not in json.dumps(events)


def test_an_error_is_recorded_by_class_only(on_app):
    client = https_client(on_app)
    assert client.get("/probe/fail").status_code == 500
    events = buffered(on_app)
    assert {"t": "error", "endpoint": "telemetry_probe.probe_fail", "error": "RuntimeError"}.items() <= events[0].items()
    assert events[1]["status"] == "500"
    assert "secret" not in json.dumps(events)


def test_website_events(on_app):
    with on_app.test_request_context():
        telemetry.event("form", form="contact", result="sent")
    [event] = buffered(on_app)
    assert event["t"] == "form" and event["result"] == "sent"


def test_the_script_tag_points_to_the_beacon(on_app):
    html = https_client(on_app).get("/probe/script").get_data(as_text=True)
    assert 'src="/_evrima/static/js/telemetry.js' in html
    assert 'data-endpoint="/_evrima/t"' in html
    assert "defer" in html


@pytest.mark.parametrize("sent, stored", [
    ({"t": "pageview", "path": "/reference?q=jana@example.com#x", "entry": True, "ref": "www.Google.com",
      "device": "mobile", "ttfb": 120.4, "dom": 450, "load": 910, "extra": "dropped"},
     {"t": "pageview", "path": "/reference", "entry": True, "ref": "google.com", "device": "mobile",
      "ttfb": 120, "dom": 450, "load": 910}),
    ({"t": "pageview", "path": "/", "entry": "yes", "ref": "<script>", "device": "fridge", "load": 10**9},
     {"t": "pageview", "path": "/", "entry": False, "ref": "", "device": "desktop"}),
    ({"t": "click", "kind": "tel", "label": "phone-contact"}, {"t": "click", "kind": "tel", "label": "phone-contact"}),
    ({"t": "click", "kind": "external", "host": "www.facebook.com", "label": "facebook"},
     {"t": "click", "kind": "external", "label": "facebook", "host": "facebook.com"}),
    ({"t": "click", "kind": "external", "host": "mapy.com"}, {"t": "click", "kind": "external", "label": "mapy.com", "host": "mapy.com"}),
    ({"t": "click", "kind": "track", "label": "cta-header"}, {"t": "click", "kind": "track", "label": "cta-header"}),
])
def test_browser_events_are_cleaned(on_app, sent, stored):
    response = browser(on_app).post("/_evrima/t", data=json.dumps(sent), content_type="application/json")
    assert response.status_code == 204
    [event] = [e for e in buffered(on_app) if e["t"] != "request"]
    assert event.pop("at").endswith("Z")
    assert event == stored


@pytest.mark.parametrize("body", [
    "not json", "[]", json.dumps({"t": "form", "form": "contact"}), json.dumps({"t": "pageview", "path": "http://x"}),
    json.dumps({"t": "click", "kind": "track"}), json.dumps({"t": "click", "kind": "external", "host": "a b"}),
    json.dumps({"t": "click", "kind": "tel", "label": "x" * 41, "number": "777"}).replace("777", "7" * 3000),
])
def test_invalid_browser_events_are_dropped(on_app, body):
    response = browser(on_app).post("/_evrima/t", data=body, content_type="application/json")
    assert response.status_code == 204
    assert [e for e in buffered(on_app) if e["t"] != "request"] == []


def test_the_beacon_needs_no_csrf_token_and_is_not_measured(on_app):
    browser(on_app).post("/_evrima/t", data=json.dumps({"t": "click", "kind": "mailto"}))
    assert [e["t"] for e in buffered(on_app)] == ["click"]


def test_the_buffer_is_capped(on_app, monkeypatch):
    monkeypatch.setattr(telemetry, "BUFFER_LIMIT", 3)
    with on_app.test_request_context():
        for number in range(5):
            telemetry.event("form", form=f"f{number}", result="sent")
    assert [e["form"] for e in buffered(on_app)] == ["f2", "f3", "f4"]


def test_shipping_sends_batches_and_empties_the_buffer(ship_app, monkeypatch):
    requests = []

    def fake_post(data):
        requests.append(json.loads(gzip.decompress(data)))
        return 202
    monkeypatch.setattr(ship, "post", fake_post)
    monkeypatch.setattr(ship, "BATCH_SIZE", 2)
    record(ship_app, 3)
    with ship_app.test_request_context():
        assert ship.ship() == 3
        assert ship._take(10) is None
    assert [len(r["events"]) for r in requests] == [2, 1]
    assert [e["form"] for r in requests for e in r["events"]] == ["f0", "f1", "f2"]
    first = requests[0]
    assert first["v"] == 1 and first["versions"]["evrima"] and first["versions"]["website"] == "fixture_site"
    assert len({r["batch"] for r in requests}) == 2
    assert buffered(ship_app) == []


@pytest.mark.parametrize("status", [0, 302, 401, 429, 503])
def test_a_refused_batch_is_sent_again_with_the_same_id(ship_app, monkeypatch, status):
    batches = []

    def fake_post(data):
        batches.append(json.loads(gzip.decompress(data)))
        return status if len(batches) == 1 else 202
    monkeypatch.setattr(ship, "post", fake_post)
    record(ship_app, 1)
    with ship_app.test_request_context():
        with pytest.raises(ship.ShipError):
            ship.ship()
    record(ship_app, 1)
    with ship_app.test_request_context():
        assert ship.ship() == 2
    assert batches[0]["batch"] == batches[1]["batch"] and batches[0]["events"] == batches[1]["events"]
    assert len(batches) == 3 and batches[2]["batch"] != batches[0]["batch"]


def test_events_pushed_to_a_full_buffer_while_sending_are_not_lost(ship_app, monkeypatch):
    """The review case: the buffer is full and new events arrive during the post."""
    monkeypatch.setattr(telemetry, "BUFFER_LIMIT", 5)
    sent = []

    def fake_post(data):
        events = json.loads(gzip.decompress(data))["events"]
        if not sent:
            record_numbers(ship_app, (10, 11, 12))
        sent.extend(e["form"] for e in events)
        return 202
    monkeypatch.setattr(ship, "post", fake_post)
    record(ship_app, 5)
    with ship_app.test_request_context():
        assert ship.ship() == 8
    assert sent == ["f0", "f1", "f2", "f3", "f4", "f10", "f11", "f12"]


def test_an_invalid_batch_is_dropped(ship_app, monkeypatch):
    monkeypatch.setattr(ship, "post", lambda data: 400)
    record(ship_app, 1)
    with ship_app.test_request_context():
        assert ship.ship() == 0
        assert ship._take(10) is None
    assert buffered(ship_app) == []


def test_only_one_shipper_runs_at_a_time(make_app, monkeypatch):
    app = make_app(env=ON)
    fake = app.extensions[redis_client._EXTENSION_KEY] = fakeredis.FakeRedis()
    monkeypatch.setattr(ship, "post", lambda data: 202)
    record(app, 1)
    fake.set(ship.LOCK_KEY, "someone-else")
    with app.test_request_context():
        assert ship.ship() == 0
        assert len(buffered(app)) == 1
        fake.delete(ship.LOCK_KEY)
        assert ship.ship() == 1
    assert fake.get(ship.LOCK_KEY) is None


def test_redis_down_is_a_ship_error(make_app):
    app = make_app(env=ON)

    class Down:
        def __getattr__(self, name):
            def fail(*args, **kwargs):
                raise redis.ConnectionError("down")
            return fail
    app.extensions[redis_client._EXTENSION_KEY] = Down()
    with app.app_context(), pytest.raises(ship.ShipError, match="Redis"):
        ship.ship()


def test_the_request_carries_the_token(on_app, monkeypatch):
    seen = {}

    class Response:
        status = 202
        def __enter__(self): return self
        def __exit__(self, *args): return False

    def fake_open(req, timeout):
        seen.update(url=req.full_url, auth=req.get_header("Authorization"), encoding=req.get_header("Content-encoding"))
        return Response()
    monkeypatch.setattr(ship._OPENER, "open", fake_open)
    with on_app.app_context():
        assert ship.post(b"x") == 202
    assert seen == {"url": "https://collector.example.com/v1/ingest", "auth": "Bearer site-token", "encoding": "gzip"}


def test_a_redirect_is_not_followed(make_app):
    """A redirect could carry the token to another address; it counts as a failure."""
    hits = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            hits.append((self.path, self.headers.get("Authorization")))
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(302)
            self.send_header("Location", "/elsewhere")
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_GET = do_POST

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        app = make_app(env={"TELEMETRY_ENDPOINT": f"http://127.0.0.1:{server.server_port}", "TELEMETRY_TOKEN": "t"})
        with app.app_context():
            assert ship.post(b"x") == 302
    finally:
        server.shutdown()
    assert hits == [("/v1/ingest", "Bearer t")]


@pytest.mark.parametrize("endpoint, ok", [
    ("https://collector.example.com", True),
    ("http://localhost:8080", True),
    ("http://127.0.0.1:8080", True),
    ("http://collector.example.com", False),
    ("http://localhost.attacker.example", False),
    ("http://localhost@attacker.example", False),
    ("https://user:pass@collector.example.com", False),
    ("https://collector.example.com/?x=1", False),
    ("https://collector.example.com:99999", False),
    ("ftp://collector.example.com", False),
])
def test_the_endpoint_is_parsed_in_production(endpoint, ok):
    environ = {"EVRIMA_ENV": "production", "SECRET_KEY": "k" * 48,
               "DATABASE_URL": "postgresql+psycopg://u:p@db/x", "REDIS_URL": "redis://r:6379/0",
               "SITE_HOSTS": "example.com", "SMTP_HOST": "smtp.example.com", "MAIL_SENDER": "w@example.com",
               "TELEMETRY_ENDPOINT": endpoint, "TELEMETRY_TOKEN": "t"}
    if ok:
        load_config(environ=environ)
    else:
        with pytest.raises(ConfigError, match="TELEMETRY_ENDPOINT"):
            load_config(environ=environ)


@pytest.mark.parametrize("headers, counted", [
    ({"Sec-Fetch-Site": "same-origin"}, True),
    ({"Sec-Fetch-Site": "cross-site"}, False),
    ({"Sec-Fetch-Site": "same-site"}, False),
    ({"Origin": "https://localhost"}, True),
    ({"Origin": "https://attacker.example"}, False),
    ({}, False),
])
def test_the_beacon_counts_only_the_websites_own_pages(on_app, headers, counted):
    https_client(on_app).post("/_evrima/t", data=json.dumps({"t": "click", "kind": "mailto"}), headers=headers,
                              base_url="https://localhost")
    assert [e["t"] for e in buffered(on_app)] == (["click"] if counted else [])


def test_a_large_body_without_length_is_not_read_whole(on_app):
    body = json.dumps({"t": "click", "kind": "mailto"}) + " " * 100_000
    browser(on_app).post("/_evrima/t", input_stream=io.BytesIO(body.encode()),
                         headers={"Transfer-Encoding": "chunked"})
    assert buffered(on_app) == []


def test_an_endpoint_needs_a_token_and_https_in_production():
    with pytest.raises(ConfigError, match="TELEMETRY_TOKEN"):
        load_config(environ={"EVRIMA_ENV": "testing", "SECRET_KEY": "k" * 48, "DATABASE_URL": "sqlite://",
                             "TELEMETRY_ENDPOINT": "https://collector.example.com"})
    with pytest.raises(ConfigError, match="https"):
        load_config(environ={"EVRIMA_ENV": "production", "SECRET_KEY": "k" * 48,
                             "DATABASE_URL": "postgresql+psycopg://u:p@db/x", "REDIS_URL": "redis://r:6379/0",
                             "SITE_HOSTS": "example.com", "SMTP_HOST": "smtp.example.com", "MAIL_SENDER": "w@example.com",
                             "TELEMETRY_ENDPOINT": "http://collector.example.com", "TELEMETRY_TOKEN": "t"})


def test_the_cleaner_rejects_non_objects():
    assert beacon.clean(None) is None
    assert beacon.clean("pageview") is None


# Telemetry level 2: a visitor id, only with consent.

LEVEL2 = {"CONSENT_CATEGORIES": ["analytics", "marketing"], "TELEMETRY_VISITORS": "analytics"}
VID = "AbCdEfGhIjKlMnOpQrStUv"


@pytest.fixture
def level2_app(make_app):
    return make_app(env=ON, blueprints=[probe], **LEVEL2)


def clicks(app):
    return [e for e in buffered(app) if e["t"] == "click"]


def test_level2_script_knows_the_category_and_the_consent_version(level2_app):
    html = https_client(level2_app).get("/probe/script").get_data(as_text=True)
    assert 'data-visitors="analytics"' in html and 'data-consent-version="1"' in html
    assert 'data-visitor-days="396"' in html


def test_level1_script_has_no_visitor_settings(on_app):
    assert "data-visitors" not in https_client(on_app).get("/probe/script").get_data(as_text=True)


@pytest.mark.parametrize("consent_cookie, vid, stored", [
    ("v1.analytics", VID, True),
    ("v1.marketing", VID, False),          # another category
    ("v0.analytics", VID, False),          # an old consent version
    (None, VID, False),                    # no choice yet
    ("v1.analytics", "short", False),      # not an id the script makes
])
def test_the_visitor_id_is_added_only_with_consent(level2_app, consent_cookie, vid, stored):
    client = browser(level2_app)
    if consent_cookie:
        client.set_cookie("evrima_consent", consent_cookie)
    client.set_cookie("evrima_vid", vid)
    client.post("/_evrima/t", data=json.dumps({"t": "click", "kind": "mailto", "vid": "from-the-body"}))
    [event] = clicks(level2_app)
    assert event.get("vid") == (VID if stored else None)


def test_level1_ignores_the_visitor_cookie(on_app):
    client = browser(on_app)
    client.set_cookie("evrima_vid", VID)
    client.post("/_evrima/t", data=json.dumps({"t": "click", "kind": "mailto"}))
    assert "vid" not in clicks(on_app)[0]


def test_withdrawn_consent_deletes_the_visitor_cookie(level2_app):
    client = browser(level2_app)
    client.set_cookie("evrima_vid", VID)
    response = client.post("/_evrima/consent", data={"choice": "selected", "category": "marketing"})
    assert any(h.startswith("evrima_vid=;") for h in response.headers.getlist("Set-Cookie"))
    assert client.get_cookie("evrima_vid") is None

    client.set_cookie("evrima_vid", VID)
    response = client.post("/_evrima/consent", data={"choice": "all"})
    assert not any(h.startswith("evrima_vid=") for h in response.headers.getlist("Set-Cookie"))


def test_level2_needs_a_consent_category(make_app):
    with pytest.raises(ConfigError, match="TELEMETRY_VISITORS"):
        make_app(env=ON, TELEMETRY_VISITORS="analytics")
