"""Rich text: what the server keeps from the editor's HTML."""

from flask import render_template_string

from evrima.editor import sanitize


def test_allowed_formatting_survives():
    html = ('<h2>Kitchens</h2><h3>Solid wood</h3><p><strong>Made</strong> to measure<br>in 6 weeks</p>'
            '<ul><li>one</li></ul><ol><li>two</li></ol>')
    assert sanitize(html) == html


def test_links_keep_their_target_and_get_a_safe_rel():
    cleaned = sanitize('<p><a href="https://example.com/" target="_blank">site</a> '
                       '<a href="mailto:a@example.com">mail</a> <a href="tel:+420123456789">call</a></p>')
    assert 'href="https://example.com/"' in cleaned
    assert 'href="mailto:a@example.com"' in cleaned
    assert 'href="tel:+420123456789"' in cleaned
    assert cleaned.count('rel="noopener noreferrer"') == 3
    assert "target" not in cleaned


def test_scripts_and_styles_disappear_with_their_content():
    cleaned = sanitize('<p>Hi</p><script>alert(1)</script><style>p{color:red}</style>'
                       '<iframe src="https://example.com"></iframe>')
    assert cleaned == "<p>Hi</p>"


def test_attributes_and_unknown_tags_are_stripped():
    cleaned = sanitize('<h1 class="x">Big</h1><p style="color:red" onclick="steal()">text '
                       '<img src="x" onerror="steal()"><span>inside</span></p>')
    assert cleaned == "Big<p>text inside</p>"


def test_dangerous_link_schemes_are_dropped():
    cleaned = sanitize('<a href="javascript:alert(1)">a</a><a href="data:text/html,x">b</a>')
    assert "javascript" not in cleaned
    assert "data:" not in cleaned


def test_bold_becomes_strong():
    assert sanitize("<p><b>bold</b></p>") == "<p><strong>bold</strong></p>"


def test_empty_input_gives_empty_text():
    assert sanitize(None) == ""
    assert sanitize("") == ""
    assert sanitize("   ") == ""


def test_rich_filter_cleans_on_output(app):
    with app.test_request_context():
        html = render_template_string("{{ text|rich }}", text='<p onclick="x()">Hi</p><script>x()</script>')
    assert html == "<p>Hi</p>"


def test_editor_field_holds_clean_escaped_html(app):
    with app.test_request_context():
        html = render_template_string(
            '{% from "evrima/admin/_macros.html" import editor %}{{ editor("body", "Text", value) }}',
            value='<p>Hi</p><script>x()</script>')
    assert "data-editor" in html
    # The cleaned HTML is the textarea's text, escaped, never live markup.
    assert "&lt;p&gt;Hi&lt;/p&gt;</textarea>" in html
    assert "script" not in html
