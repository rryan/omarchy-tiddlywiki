import io
import json
import unittest
from unittest.mock import patch

import tiddlywiki


CONFIG = {"url": "https://wiki.invalid", "username": "test-user", "password": "test-secret"}


class Response(io.BytesIO):
    status = 200


class FakeOpener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return Response(value.encode() if isinstance(value, str) else json.dumps(value).encode())


class ClientTests(unittest.TestCase):
    def test_read_only_index_retains_text_and_normalizes_tags_without_system_or_binary_bodies(self):
        opener = FakeOpener([
            {"anonymous": False, "read_only": True, "space": {"recipe": "a/b"}},
            [{"title": "Note", "text": "search me", "tags": "one [[two words]] one"},
             {"title": "$:/System", "text": "hidden"},
             {"title": "Photo", "type": "image/png", "text": "base64-data", "tags": ["asset"]}],
        ])
        with patch("tiddlywiki.urllib.request.build_opener", return_value=opener):
            result = tiddlywiki.index(CONFIG)
        self.assertEqual(result["tiddlers"], [
            {"title": "Note", "text": "search me", "tags": ["one", "two words"], "type": "text/vnd.tiddlywiki"},
            {"title": "Photo", "type": "image/png", "text": "", "tags": ["asset"]},
        ])
        self.assertEqual(opener.requests[1].full_url, "https://wiki.invalid/recipes/a%2Fb/tiddlers.json?exclude=bag")
        self.assertTrue(all(request.get_method() == "GET" for request in opener.requests))

    def test_read_fetches_fresh_fields_and_rendered_html_for_exact_encoded_title(self):
        title = "A / café?#"
        opener = FakeOpener([
            {"anonymous": False, "read_only": True},
            {"title": title, "text": "fresh source", "tags": ["tag"], "creator": "Author",
             "modifier": "Editor", "created": "20260102030405000", "modified": "20260203040506000"},
            '<html><head><style>bad</style></head><body><h1 class="tc-site-title">Wiki title</h1>'
            '<div class="tc-site-subtitle">Wiki subtitle</div><div class="tc-tiddler-frame">'
            '<div class="tc-tiddler-title">Repeated title</div><div class="tc-subtitle">Repeated metadata</div>'
            '<div class="tc-tags-wrapper">Repeated tags</div><div class="tc-tiddler-body tc-clearfix">'
            '<h1>Body heading</h1><p onclick="bad()">Rendered <a href="https://remote.invalid">link</a>'
            '<img src="https://remote.invalid/pic"></p></div><p>After body</p></div></body></html>',
        ])
        with patch("tiddlywiki.urllib.request.build_opener", return_value=opener):
            result = tiddlywiki.read_tiddler(CONFIG, {"title": title})
        self.assertIn("<h1>Body heading</h1>", result["html"])
        self.assertIn("Rendered link", result["html"])
        for excluded in ("Wiki title", "Wiki subtitle", "Repeated", "After body", "onclick", "href", "src", "remote.invalid"):
            self.assertNotIn(excluded, result["html"])
        self.assertEqual(opener.requests[1].full_url, "https://wiki.invalid/recipes/default/tiddlers/A%20%2F%20caf%C3%A9%3F%23")
        self.assertEqual(opener.requests[2].full_url, "https://wiki.invalid/A%20%2F%20caf%C3%A9%3F%23")
        self.assertTrue(all(request.get_method() == "GET" for request in opener.requests))

    def test_missing_or_truncated_body_is_a_controlled_read_error(self):
        for markup in (
            '<html><body><h1 class="tc-site-title">Not the tiddler</h1></body></html>',
            '<template><div class="tc-tiddler-body">Not a visible body</div></template>',
            '<div class="tc-tiddler-body"><p>Incomplete',
        ):
            with self.subTest(markup=markup):
                opener = FakeOpener([{"anonymous": False}, {"title": "Note"}, markup])
                with patch("tiddlywiki.urllib.request.build_opener", return_value=opener):
                    with self.assertRaises(tiddlywiki.WikiError):
                        tiddlywiki.read_tiddler(CONFIG, {"title": "Note"})

    def test_anonymous_is_refused_and_read_only_cannot_create(self):
        for status, operation in [
            ({"anonymous": True}, lambda: tiddlywiki.index(CONFIG)),
            ({"anonymous": False, "read_only": True}, lambda: tiddlywiki.create(CONFIG, {"title": "New", "type": "text/plain"})),
        ]:
            opener = FakeOpener([status])
            with patch("tiddlywiki.urllib.request.build_opener", return_value=opener):
                with self.assertRaises(tiddlywiki.WikiError):
                    operation()
            self.assertEqual([request.get_method() for request in opener.requests], ["GET"])

    def test_existing_title_is_never_overwritten(self):
        opener = FakeOpener([{"anonymous": False, "read_only": False}, {"title": "Existing"}])
        with patch("tiddlywiki.urllib.request.build_opener", return_value=opener):
            with self.assertRaisesRegex(tiddlywiki.WikiError, "already exists"):
                tiddlywiki.create(CONFIG, {"title": "Existing", "type": "text/plain"})
        self.assertEqual([request.get_method() for request in opener.requests], ["GET", "GET"])

    def test_system_reader_and_creator_are_refused_before_network(self):
        with patch("tiddlywiki.urllib.request.build_opener") as build:
            with self.assertRaises(tiddlywiki.WikiError):
                tiddlywiki.read_tiddler(CONFIG, {"title": "$:/System"})
            with self.assertRaises(tiddlywiki.WikiError):
                tiddlywiki.create(CONFIG, {"title": "$:/System", "type": "text/plain"})
            build.assert_not_called()


class SanitizerTests(unittest.TestCase):
    def test_unsafe_subtrees_and_attributes_are_removed_but_formatting_remains(self):
        markup = '<!doctype html><head><title>secret</title></head><p style="background:url(remote)">Safe &lt;word&gt;</p><script>alert(1)</script><form><p>secret form</p></form><iframe>secret frame</iframe><svg><text>secret svg</text></svg><video>secret media</video><table background="remote"><tr><td onclick="bad()">Cell</td></tr></table><a href="file:///secret">Label</a><img src="remote"><embed src="remote">End'
        rendered = tiddlywiki.sanitize_html(markup)
        for content in ("Safe &lt;word&gt;", "<table>", "<td>Cell</td>", "Label", "End"):
            self.assertIn(content, rendered)
        for excluded in ("secret", "alert", "remote", "file:", "onclick", "style=", "<img", "<embed", "<a "):
            self.assertNotIn(excluded, rendered)

    def test_malformed_tags_cannot_reintroduce_attributes_or_unescape_markup(self):
        rendered = tiddlywiki.sanitize_html('<p><strong>hello</p>&lt;img src=x&gt;<script>unfinished')
        self.assertIn("<strong>hello</strong>", rendered)
        self.assertIn("&lt;img src=x&gt;", rendered)
        self.assertNotIn("<img", rendered)
        self.assertNotIn("unfinished", rendered)

    def test_body_selection_preserves_nested_content_and_same_named_classes(self):
        markup = '<div class="tc-tiddler-frame"><div class="tc-tiddler-body-extra">Wrong boundary</div>' \
            '<div class="tc-clearfix tc-tiddler-body"><div class="tc-tiddler-body">' \
            '<h1 class="tc-site-title">Body title &amp; details</h1>' \
            '<div class="tc-site-subtitle">Body subtitle</div><div class="tc-tiddler-title">Inner title</div>' \
            '<div class="tc-subtitle">Inner metadata</div><div class="tc-tags-wrapper">Inner tags</div>' \
            '<span/><br><hr/><img src="remote"><input value="secret"><p>After void nodes</p></div>' \
            '<p>After nested body &lt;script&gt; &quot;quoted&quot;</p></div><p>Outside tail</p></div>'
        rendered = tiddlywiki.sanitize_tiddler_html(markup)
        for content in ("Body title &amp; details", "Body subtitle", "Inner title", "Inner metadata",
                        "Inner tags", "<br>", "<hr>", "After void nodes", "After nested body",
                        "&lt;script&gt;", "&quot;quoted&quot;"):
            self.assertIn(content, rendered)
        for excluded in ("Wrong boundary", "Outside tail", "class=", "src=", "remote", "secret"):
            self.assertNotIn(excluded, rendered)

    def test_dangerous_subtrees_cannot_supply_a_body_or_active_content(self):
        markup = '<head><div class="tc-tiddler-body">Head decoy</div></head>' \
            '<template><div class="tc-tiddler-body">Template decoy</div></template>' \
            '<svg><foreignObject><div class="tc-tiddler-body">SVG decoy</div></foreignObject></svg>' \
            '<div class="tc-tiddler-body"><p style="background:url(remote)">Safe</p>' \
            '<script>active()</script><form><div><p>Hidden form</p></div></form>' \
            '<iframe>Hidden frame</iframe><svg><text>Hidden SVG</text></svg>' \
            '<template><p>Hidden template</p></template><picture><img src="remote"/>Hidden picture</picture>' \
            '<a href="file:///secret" onclick="active()">Visible link</a>&lt;img src=x&gt;' \
            '<p>Safe tail</p></div><script>outside()</script>'
        rendered = tiddlywiki.sanitize_tiddler_html(markup)
        for content in ("<p>Safe</p>", "Visible link", "&lt;img src=x&gt;", "<p>Safe tail</p>"):
            self.assertIn(content, rendered)
        for excluded in ("decoy", "Hidden", "active()", "outside()", "remote", "file:", "onclick",
                         "style=", "href=", "<script", "<img", "<iframe", "<svg"):
            self.assertNotIn(excluded, rendered)

    def test_self_closing_body_is_empty_without_including_following_chrome(self):
        rendered = tiddlywiki.sanitize_tiddler_html('<div class="tc-tiddler-body"/><p>Outside</p>')
        self.assertEqual(rendered, "")

    def test_nontext_has_no_source_body_and_no_active_preview(self):
        opener = FakeOpener([
            {"anonymous": False},
            {"title": "Photo", "type": "image/png", "text": "base64"},
            '<div class="tc-tiddler-frame"><h1>Photo title</h1><div class="tc-tiddler-body">'
            '<p><img src="data:image/png;base64,payload"></p></div></div>',
        ])
        with patch("tiddlywiki.urllib.request.build_opener", return_value=opener):
            result = tiddlywiki.read_tiddler(CONFIG, {"title": "Photo"})
        self.assertEqual(result["tiddler"]["text"], "")
        self.assertIn("no static text preview", result["html"])
        for excluded in ("base64", "payload", "src=", "<img", "Photo title"):
            self.assertNotIn(excluded, result["html"])


if __name__ == "__main__":
    unittest.main()
