"""Rich text: the minimal editor's server side.

The editor in the admin (admin.js, data-editor) produces a little HTML. The
server never trusts it: every rich text is cleaned with nh3 when it is saved
(`sanitize`) and again when it is shown (the `rich` template filter), so a
crafted request or an old database row cannot put scripts, styles or event
handlers on a page.

What stays (docs/framework.md, decided after the audit): paragraphs, line
breaks, headings h2 and h3, bold, links and lists. Everything else is either
unwrapped (its text kept) or, for script-like elements, dropped with its
content. Inline styles never survive, so the design of the website decides
how text looks, and the strict CSP holds.
"""

import nh3
from flask import Flask
from markupsafe import Markup

ALLOWED_TAGS = {"p", "br", "h2", "h3", "strong", "a", "ul", "ol", "li"}
ALLOWED_ATTRIBUTES = {"a": {"href"}}
# Links may go to websites, e-mail addresses and phone numbers; never to
# javascript: or data: URLs.
ALLOWED_URL_SCHEMES = {"http", "https", "mailto", "tel"}
# Removed together with everything inside them, not just unwrapped.
DROPPED_WITH_CONTENT = {"script", "style", "template", "iframe", "object", "embed", "noscript"}


def sanitize(html: str | None) -> str:
    """Return `html` reduced to the allowed tags and attributes."""
    if not html:
        return ""
    # Editors sometimes produce <b> for bold; keep the meaning as <strong>.
    html = html.replace("<b>", "<strong>").replace("</b>", "</strong>")
    cleaned = nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        clean_content_tags=DROPPED_WITH_CONTENT,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_URL_SCHEMES,
        link_rel="noopener noreferrer",
    )
    return cleaned.strip()


def rich(html: str | None) -> Markup:
    """Template filter: clean rich text and mark it safe for output."""
    return Markup(sanitize(html))


def init_app(app: Flask) -> None:
    """Register the template helpers.

    `rich` shows stored rich text: {{ reference.description | rich }}.
    `sanitize_html` fills the editor's field (as escaped text) in forms.
    """
    app.jinja_env.filters["rich"] = rich
    app.jinja_env.globals["sanitize_html"] = sanitize
