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
            {"title": title, "text": "fresh source", "tags": ["tag"]},
            '<html><head><style>bad</style></head><body><p onclick="bad()">Rendered <a href="https://remote.invalid">link</a><img src="https://remote.invalid/pic"></p></body></html>',
        ])
        with patch("tiddlywiki.urllib.request.build_opener", return_value=opener):
            result = tiddlywiki.read_tiddler(CONFIG, {"title": title})
        self.assertEqual(result["html"], "<p>Rendered link</p>")
        self.assertEqual(opener.requests[1].full_url, "https://wiki.invalid/recipes/default/tiddlers/A%20%2F%20caf%C3%A9%3F%23")
        self.assertEqual(opener.requests[2].full_url, "https://wiki.invalid/A%20%2F%20caf%C3%A9%3F%23")
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
    def test_unsafe_subtrees_and_attributes_are_removed_but_formatting_remains(self):
        markup = '<!doctype html><head><title>secret</title></head><p style="background:url(remote)">Safe &lt;word&gt;</p><script>alert(1)</script><form><p>secret form</p></form><iframe>secret frame</iframe><svg><text>secret svg</text></svg><video>secret media</video><table background="remote"><tr><td onclick="bad()">Cell</td></tr></table><a href="file:///secret">Label</a><img src="remote"><embed src="remote">End'
        self.assertEqual(tiddlywiki.sanitize_html(markup), '<p>Safe &lt;word&gt;</p><table><tr><td>Cell</td></tr></table>LabelEnd')

    def test_malformed_tags_cannot_reintroduce_attributes_or_unescape_markup(self):
        self.assertEqual(tiddlywiki.sanitize_html('<p><strong>hello</p>&lt;img src=x&gt;<script>unfinished'), '<p><strong>hello</strong></p>&lt;img src=x&gt;')

    def test_nontext_has_no_source_body_and_no_active_preview(self):
        opener = FakeOpener([
            {"anonymous": False},
            {"title": "Photo", "type": "image/png", "text": "base64"},
            '<div><p><img src="data:image/png;base64,payload"></p></div>',
        ])
        with patch("tiddlywiki.urllib.request.build_opener", return_value=opener):
            result = tiddlywiki.read_tiddler(CONFIG, {"title": "Photo"})
        self.assertEqual(result["tiddler"]["text"], "")
        self.assertEqual(result["html"], '<p>This non-text tiddler has no static text preview.</p>')


if __name__ == "__main__":
    unittest.main()
