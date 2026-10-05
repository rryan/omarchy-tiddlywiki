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

    def test_arbitrary_titles_render_fresh_body_and_nested_cached_transclusions(self):
        cases = (
            ("2023/11/14 fsb@ chat", "2023%2F11%2F14%20fsb%40%20chat"),
            ("literal % and ? and #", "literal%20%25%20and%20%3F%20and%20%23"),
            ("日記 / café @ 100%?#", "%E6%97%A5%E8%A8%98%20%2F%20caf%C3%A9%20%40%20100%25%3F%23"),
            ("GettingStarted", "GettingStarted"),
        )
        for title, encoded_title in cases:
            with self.subTest(title=title):
                nested_title = "Nested / %?#@ café"
                leaf_title = "Leaf / %?#@ 日本語"
                fields = {"title": title,
                          "text": "! Fresh heading\n\n{{" + nested_title + "}}",
                          "tags": "tag [[two words]]", "creator": "Author", "modifier": "Editor",
                          "created": "20260102030405000", "modified": "20260203040506000"}
                context = [
                    {"title": title, "text": "Stale cached source", "type": "text/vnd.tiddlywiki", "tags": []},
                    {"title": nested_title, "text": "{{" + leaf_title + "}}",
                     "type": "text/vnd.tiddlywiki", "tags": []},
                    {"title": leaf_title, "text": "''Nested leaf content''",
                     "type": "text/vnd.tiddlywiki", "tags": []},
                ]
                opener = FakeOpener([{"anonymous": False, "read_only": True,
                                      "space": {"recipe": "a/b"}}, fields])
                with patch("tiddlywiki.urllib.request.build_opener", return_value=opener):
                    result = tiddlywiki.read_tiddler(CONFIG, {"title": title, "context": context})
                self.assertIn("<h1>Fresh heading</h1>", result["html"])
                self.assertIn("<strong>Nested leaf content</strong>", result["html"])
                self.assertNotIn("Stale cached source", result["html"])
                self.assertEqual([request.full_url for request in opener.requests], [
                    "https://wiki.invalid/status",
                    "https://wiki.invalid/recipes/a%2Fb/tiddlers/" + encoded_title,
                ])
                self.assertTrue(all(request.get_method() == "GET" for request in opener.requests))
                self.assertTrue(all(request.get_header("Accept") == "application/json"
                                    for request in opener.requests))

    def test_markdown_types_render_formatting_without_active_attributes(self):
        for content_type in ("text/x-markdown", "text/markdown"):
            with self.subTest(content_type=content_type):
                opener = FakeOpener([
                    {"anonymous": False},
                    {"title": "Markdown", "type": content_type,
                     "text": "# Markdown heading\n\n**Strong text** and [Visible link](https://remote.invalid)\n\n"
                             '<img src="https://remote.invalid/pic" onerror="active()">'},
                ])
                with patch("tiddlywiki.urllib.request.build_opener", return_value=opener):
                    result = tiddlywiki.read_tiddler(CONFIG, {"title": "Markdown"})
                for content in ("<h1>Markdown heading</h1>", "<strong>Strong text</strong>", "Visible link"):
                    self.assertIn(content, result["html"])
                for excluded in ("remote.invalid", "href=", "src=", "onerror", "<img"):
                    self.assertNotIn(excluded, result["html"])

    def test_context_cannot_replace_trusted_core_or_execute_remote_modules(self):
        hostile_code = 'exports.name = "hostile"; exports.run = function() { throw new Error("REMOTE MODULE EXECUTED"); };'
        context = [
            {"title": "$:/core/ui/ViewTemplate/body/default", "type": "text/vnd.tiddlywiki",
             "text": "UNTRUSTED CORE OVERRIDE"},
            {"title": "$:/core", "type": "application/json", "plugin-type": "plugin",
             "text": json.dumps({"tiddlers": {"$:/core/modules/macros/hostile": {
                 "title": "$:/core/modules/macros/hostile", "type": "application/javascript",
                 "module-type": "macro", "text": hostile_code}}})},
            {"title": "ordinary javascript", "type": "application/javascript",
             "module-type": "macro", "text": hostile_code},
            {"title": "ordinary plugin", "type": "application/json", "plugin-type": "plugin",
             "text": json.dumps({"tiddlers": {"$:/core/modules/macros/hostile": {
                 "title": "$:/core/modules/macros/hostile", "type": "application/javascript",
                 "module-type": "macro", "text": hostile_code}}})},
        ]
        opener = FakeOpener([{"anonymous": False},
                             {"title": "Safe", "text": "''Trusted rendering survives''\n\n<<hostile>>"}])
        with patch("tiddlywiki.urllib.request.build_opener", return_value=opener):
            result = tiddlywiki.read_tiddler(CONFIG, {"title": "Safe", "context": context})
        self.assertIn("<strong>Trusted rendering survives</strong>", result["html"])
        self.assertNotIn("REMOTE MODULE EXECUTED", result["html"])
        self.assertNotIn("UNTRUSTED CORE OVERRIDE", result["html"])

    def test_missing_node_is_a_safe_actionable_read_error(self):
        opener = FakeOpener([{"anonymous": False},
                             {"title": "Private title", "text": "Private body"}])
        with patch("tiddlywiki.urllib.request.build_opener", return_value=opener):
            with patch.dict("os.environ", {"PATH": ""}):
                with self.assertRaises(tiddlywiki.WikiError) as caught:
                    tiddlywiki.read_tiddler(CONFIG, {"title": "Private title"})
        message = str(caught.exception)
        self.assertIn("Node.js", message)
        for private in ("Private title", "Private body", CONFIG["username"], CONFIG["password"]):
            self.assertNotIn(private, message)

    def test_renderer_timeout_is_safe_and_does_not_fetch_remote_html(self):
        opener = FakeOpener([{"anonymous": False}, {"title": "Private", "text": "Secret body"}])
        timeout = tiddlywiki.subprocess.TimeoutExpired(
            ["node", "renderer.js"], 30, output="Secret body", stderr="Private stack")
        with patch("tiddlywiki.urllib.request.build_opener", return_value=opener):
            with patch("tiddlywiki.subprocess.run", side_effect=timeout):
                with self.assertRaises(tiddlywiki.WikiError) as caught:
                    tiddlywiki.read_tiddler(CONFIG, {"title": "Private"})
        for private in ("Secret body", "Private stack", CONFIG["username"], CONFIG["password"]):
            self.assertNotIn(private, str(caught.exception))
        self.assertEqual([request.full_url for request in opener.requests], [
            "https://wiki.invalid/status", "https://wiki.invalid/recipes/default/tiddlers/Private"])
        self.assertTrue(all(request.get_method() == "GET" for request in opener.requests))

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
    def test_missing_or_truncated_body_is_a_controlled_sanitizer_error(self):
        for markup in (
            '<html><body><h1 class="tc-site-title">Not the tiddler</h1></body></html>',
            '<template><div class="tc-tiddler-body">Not a visible body</div></template>',
            '<div class="tc-tiddler-body"><p>Incomplete',
        ):
            with self.subTest(markup=markup):
                with self.assertRaises(tiddlywiki.WikiError):
                    tiddlywiki.sanitize_tiddler_html(markup)

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
        ])
        with patch("tiddlywiki.urllib.request.build_opener", return_value=opener):
            result = tiddlywiki.read_tiddler(CONFIG, {"title": "Photo"})
        self.assertEqual(result["tiddler"]["text"], "")
        self.assertIn("no static text preview", result["html"])
        for excluded in ("base64", "payload", "src=", "<img", "Photo title"):
            self.assertNotIn(excluded, result["html"])


if __name__ == "__main__":
    unittest.main()
