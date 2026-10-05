import datetime
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
                self.assertFalse(result["editable"])
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
        for content_type in ("text/x-markdown", "text/markdown", "Text/Markdown; charset=UTF-8"):
            with self.subTest(content_type=content_type):
                opener = FakeOpener([
                    {"anonymous": False},
                    {"title": "Markdown", "type": content_type,
                     "text": "# Markdown heading\n\n**Strong text** and [Visible link](https://remote.invalid)\n\n"
                             '<img src="https://remote.invalid/pic" onerror="active()">'},
                ])
                with patch("tiddlywiki.urllib.request.build_opener", return_value=opener):
                    result = tiddlywiki.read_tiddler(CONFIG, {"title": "Markdown"})
                self.assertTrue(result["editable"])
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
            with self.assertRaises(tiddlywiki.WikiError):
                tiddlywiki.create(CONFIG, {"title": "Existing", "type": "text/plain"})
        self.assertEqual([request.get_method() for request in opener.requests], ["GET", "GET"])

    def test_system_reader_and_creator_are_refused_before_network(self):
        with patch("tiddlywiki.urllib.request.build_opener") as build:
            with self.assertRaises(tiddlywiki.WikiError):
                tiddlywiki.read_tiddler(CONFIG, {"title": "$:/System"})
            with self.assertRaises(tiddlywiki.WikiError):
                tiddlywiki.create(CONFIG, {"title": "$:/System", "type": "text/plain"})
            build.assert_not_called()


class PrepareTests(unittest.TestCase):
    def prepare_at(self, opener, kind, now=None):
        if now is None:
            now = datetime.datetime(2026, 10, 5, 12, 0)
        with patch("tiddlywiki.urllib.request.build_opener", return_value=opener), \
                patch("tiddlywiki.datetime.datetime") as clock:
            clock.now.return_value = now
            return tiddlywiki.prepare(CONFIG, {"kind": kind})

    def run_cli(self, draft, opener):
        stdout = io.StringIO()
        with patch("tiddlywiki.urllib.request.build_opener", return_value=opener), \
                patch("builtins.open", return_value=io.StringIO(json.dumps(CONFIG))), \
                patch("sys.argv", ["tiddlywiki.py", "prepare"]), \
                patch("sys.stdin", io.StringIO(json.dumps(draft) + "\n")), \
                patch("sys.stdout", stdout):
            tiddlywiki.main()
        return json.loads(stdout.getvalue())

    def test_absent_today_uses_local_date_across_year_and_day_boundaries(self):
        for now, date in (
            (datetime.datetime(2027, 1, 1, 0, 1,
                               tzinfo=datetime.timezone(datetime.timedelta(hours=14))), "2027/1/1"),
            (datetime.datetime(2026, 12, 31, 23, 59,
                               tzinfo=datetime.timezone(datetime.timedelta(hours=-12))), "2026/12/31"),
            (datetime.datetime(2026, 2, 9, 0, 0), "2026/2/9"),
        ):
            with self.subTest(date=date):
                body = io.BytesIO(b"Private not-found body")
                missing = tiddlywiki.urllib.error.HTTPError(
                    "https://wiki.invalid", 404, "Missing", {}, body)
                opener = FakeOpener([
                    {"anonymous": False, "read_only": False, "space": {"recipe": "a/b ?#"}},
                    missing,
                ])
                result = self.prepare_at(opener, "today", now)
                self.assertEqual(result, {
                    "ok": True, "kind": "today", "date": date, "mode": "create",
                    "fields": {"title": date, "text": "", "type": "text/x-markdown", "tags": ["Journal"]},
                    "tags": ["Journal"],
                })
                self.assertTrue(body.closed)
                self.assertEqual(opener.requests[-1].full_url,
                                 "https://wiki.invalid/recipes/a%2Fb%20%3F%23/tiddlers/" +
                                 tiddlywiki.urllib.parse.quote(date, safe=""))
                self.assertEqual([req.get_method() for req in opener.requests], ["GET", "GET"])

    def test_existing_today_retains_full_baseline_and_suggests_journal_without_mutation(self):
        for tags, original_tags, suggested_tags in (
            ("personal [[two words]] personal", ["personal", "two words"], ["personal", "two words", "Journal"]),
            (["personal", "Journal", "Journal", "two words"], ["personal", "Journal", "two words"],
             ["personal", "Journal", "two words"]),
        ):
            with self.subTest(tags=tags):
                server = {
                    "title": "2026/10/5", "text": "Keep my journal", "tags": tags,
                    "created": "20261005000100000", "modified": "20261005010200000",
                    "creator": "Original author", "modifier": "Earlier editor",
                    "custom-field": "Keep me", "custom-list": ["first", "second"],
                }
                opener = FakeOpener([{"anonymous": False}, server])
                result = self.prepare_at(opener, "today")
                self.assertEqual(result["mode"], "edit")
                self.assertEqual(result["fields"], {
                    **server, "tags": original_tags, "type": "text/vnd.tiddlywiki",
                })
                self.assertEqual(result["tags"], suggested_tags)
                result["tags"].append("draft-only")
                self.assertEqual(result["fields"]["tags"], original_tags)
                self.assertEqual(server["tags"], tags)
                self.assertEqual([req.get_method() for req in opener.requests], ["GET", "GET"])

    def test_prepared_today_baseline_can_be_updated_without_losing_metadata(self):
        server = {"title": "2026/10/5", "text": "Old journal", "tags": ["personal"],
                  "type": "text/x-markdown", "created": "20261005000100000",
                  "custom-field": "Keep me", "custom-list": ["first", "second"]}
        opener = FakeOpener([{"anonymous": False}, server, {"anonymous": False}, server, {}])
        prepared = self.prepare_at(opener, "today")
        self.assertEqual([req.get_method() for req in opener.requests], ["GET", "GET"])
        draft = {"title": prepared["fields"]["title"], "original": prepared["fields"],
                 "text": "Updated journal", "type": prepared["fields"]["type"],
                 "tags": " ".join(prepared["tags"])}
        with patch("tiddlywiki.urllib.request.build_opener", return_value=opener):
            result = tiddlywiki.update(CONFIG, draft)
        self.assertEqual(result, {"ok": True, "title": "2026/10/5"})
        saved = json.loads(opener.requests[-1].data)
        self.assertEqual(saved["text"], "Updated journal")
        self.assertEqual(saved["tags"], ["personal", "Journal"])
        for field in ("created", "custom-field", "custom-list"):
            self.assertEqual(saved[field], server[field])
        self.assertEqual(prepared["fields"], server)

    def test_quick_note_uses_fresh_index_and_lowest_unused_exact_positive_number(self):
        unrelated = [
            {"title": "2026/10/4 Quick Note 2"},
            {"title": "2026/10/5 Quick Note 0"},
            {"title": "2026/10/5 Quick Note 02"},
            {"title": "2026/10/5 Quick Note 2 extra"},
            {"title": "$:/2026/10/5 Quick Note 2"},
        ]
        opener = FakeOpener([
            {"anonymous": False, "space": {"recipe": "a/b"}},
            unrelated + [{"title": "2026/10/5 Quick Note 1"}, {"title": "2026/10/5 Quick Note 3"}],
            {"anonymous": False, "space": {"recipe": "a/b"}},
            unrelated + [{"title": f"2026/10/5 Quick Note {number}"} for number in (1, 2, 3)],
            {"anonymous": False, "space": {"recipe": "a/b"}}, [],
        ])
        for number in (2, 4, 1):
            with self.subTest(number=number):
                result = self.prepare_at(opener, "quick-note")
                self.assertEqual(result, {
                    "ok": True, "kind": "quick-note", "date": "2026/10/5", "mode": "create",
                    "fields": {"title": f"2026/10/5 Quick Note {number}", "text": "",
                               "type": "text/x-markdown", "tags": ["Note"]},
                    "tags": ["Note"],
                })
        self.assertEqual([req.full_url for req in opener.requests], [
            url for _ in range(3) for url in (
                "https://wiki.invalid/status", "https://wiki.invalid/recipes/a%2Fb/tiddlers.json?exclude=bag")
        ])
        self.assertTrue(all(req.get_method() == "GET" for req in opener.requests))

    def test_readonly_and_anonymous_refuse_both_preparation_modes_without_writes(self):
        for kind in ("today", "quick-note"):
            for status in ({"anonymous": True}, {"read_only": False},
                           {"anonymous": False, "read_only": True}):
                with self.subTest(kind=kind, status=status):
                    opener = FakeOpener([status])
                    with self.assertRaises(tiddlywiki.WikiError):
                        self.prepare_at(opener, kind)
                    self.assertEqual([req.get_method() for req in opener.requests], ["GET"])

    def test_binary_wrong_title_and_invalid_today_body_are_refused_without_writes(self):
        for fields in (
            {"title": "2026/10/5", "type": "image/png", "text": "base64"},
            {"title": "Wrong title", "text": "Private journal"},
            {"title": "2026/10/5", "text": ["invalid body"]},
            {"title": "2026/10/5", "tags": ["safe", {"invalid": "tag"}]},
            {"title": "2026/10/5", "tags": "[[unfinished"},
        ):
            with self.subTest(fields=fields):
                opener = FakeOpener([{"anonymous": False}, fields])
                with self.assertRaises(tiddlywiki.WikiError):
                    self.prepare_at(opener, "today")
                self.assertEqual([req.get_method() for req in opener.requests], ["GET", "GET"])

    def test_missing_or_malicious_kind_is_a_safe_cli_error_before_network(self):
        for draft in ({}, {"kind": "$:/System"}, {"kind": "../private?secret"},
                      {"kind": ["today"]}, {"kind": None}, []):
            with self.subTest(draft=draft):
                opener = FakeOpener([])
                result = self.run_cli(draft, opener)
                self.assertFalse(result["ok"])
                self.assertNotIn("private", result["error"])
                self.assertEqual(opener.requests, [])

    def test_cli_prepares_without_using_client_title_or_cached_index(self):
        opener = FakeOpener([{"anonymous": False}, [{"title": "2026/10/5 Quick Note 1"}]])
        now = datetime.datetime(2026, 10, 5, 12, 0)
        with patch("tiddlywiki.datetime.datetime") as clock:
            clock.now.return_value = now
            result = self.run_cli({"kind": "quick-note", "title": "$:/System",
                                   "context": [], "text": "Do not save me"}, opener)
        self.assertEqual(result["fields"]["title"], "2026/10/5 Quick Note 2")
        self.assertEqual(result["fields"]["text"], "")
        self.assertEqual([req.get_method() for req in opener.requests], ["GET", "GET"])

    def test_invalid_fresh_index_fails_safely_without_writes(self):
        for index in ({"private": "Not an index"}, [{"title": 42}], [None]):
            with self.subTest(index=index):
                opener = FakeOpener([{"anonymous": False}, index])
                result = self.run_cli({"kind": "quick-note"}, opener)
                self.assertFalse(result["ok"])
                self.assertNotIn("private", result["error"])
                self.assertEqual([req.get_method() for req in opener.requests], ["GET", "GET"])

    def test_prepare_http_errors_are_closed_and_private_diagnostics_are_redacted(self):
        for kind in ("today", "quick-note"):
            for code in (302, 403, 500):
                with self.subTest(kind=kind, code=code):
                    body = io.BytesIO(b"Private server body")
                    failure = tiddlywiki.urllib.error.HTTPError(
                        "https://private.invalid", code, "Private server stack test-secret", {}, body)
                    opener = FakeOpener([{"anonymous": False}, failure])
                    result = self.run_cli({"kind": kind}, opener)
                    self.assertFalse(result["ok"])
                    self.assertIn(f"HTTP {code}", result["error"])
                    for secret in ("Private", "private.invalid", CONFIG["password"], CONFIG["username"]):
                        self.assertNotIn(secret, result["error"])
                    self.assertTrue(body.closed)
                    self.assertEqual([req.get_method() for req in opener.requests], ["GET", "GET"])

    def test_prepare_network_error_does_not_expose_private_diagnostics(self):
        opener = FakeOpener([
            {"anonymous": False},
            tiddlywiki.urllib.error.URLError("Private server stack test-secret"),
        ])
        result = self.run_cli({"kind": "today"}, opener)
        self.assertFalse(result["ok"])
        for secret in ("Private", CONFIG["password"], CONFIG["username"]):
            self.assertNotIn(secret, result["error"])
        self.assertEqual([req.get_method() for req in opener.requests], ["GET", "GET"])


class UpdateTests(unittest.TestCase):
    def baseline(self):
        return {"title": "Note / café", "text": "Old body", "type": "text/plain",
                "tags": ["old"], "created": "20260102030405000",
                "creator": "Original author", "modified": "20260103030405000",
                "modifier": "Earlier editor", "custom-field": "Keep me",
                "custom-list": ["first", "second"]}

    def draft(self, original):
        return {"title": original["title"], "original": original,
                "text": "New body", "type": "text/markdown", "tags": "new [[two words]] new"}

    def test_update_preserves_metadata_and_changes_only_editable_and_modification_fields(self):
        original = self.baseline()
        server = {**original, "tags": "old"}
        opener = FakeOpener([
            {"anonymous": False, "username": "Current editor", "space": {"recipe": "a/b"}},
            server, {},
        ])
        fixed = datetime.datetime(2026, 10, 4, 12, 13, 14, 123000, tzinfo=datetime.timezone.utc)
        with patch("tiddlywiki.urllib.request.build_opener", return_value=opener):
            with patch("tiddlywiki.datetime.datetime") as clock:
                clock.now.return_value = fixed
                result = tiddlywiki.update(CONFIG, self.draft(original))
        self.assertEqual(result, {"ok": True, "title": original["title"]})
        self.assertEqual([req.get_method() for req in opener.requests], ["GET", "GET", "PUT"])
        saved = json.loads(opener.requests[-1].data)
        self.assertEqual(saved, {
            **original, "text": "New body", "type": "text/markdown", "tags": ["new", "two words"],
            "modified": "20261004121314123", "modifier": "Current editor",
        })
        self.assertEqual(opener.requests[-1].full_url,
                         "https://wiki.invalid/recipes/a%2Fb/tiddlers/Note%20%2F%20caf%C3%A9")
        self.assertEqual(original, self.baseline())

    def test_changes_in_any_original_field_prevent_put(self):
        original = self.baseline()
        for change in ({"text": "Other writer"}, {"tags": ["other"]},
                       {"type": "text/markdown"}, {"custom-field": "Changed"},
                       {"created": "20260201000000000"}, {"new-field": "Added"}):
            with self.subTest(change=change):
                opener = FakeOpener([{"anonymous": False}, {**original, **change}])
                with patch("tiddlywiki.urllib.request.build_opener", return_value=opener):
                    with self.assertRaises(tiddlywiki.WikiError):
                        tiddlywiki.update(CONFIG, self.draft(original))
                self.assertEqual([req.get_method() for req in opener.requests], ["GET", "GET"])

    def test_missing_tiddler_does_not_recreate_it(self):
        missing = tiddlywiki.urllib.error.HTTPError("https://wiki.invalid", 404, "Missing", {}, None)
        opener = FakeOpener([{"anonymous": False}, missing])
        with patch("tiddlywiki.urllib.request.build_opener", return_value=opener):
            with self.assertRaises(tiddlywiki.WikiError):
                tiddlywiki.update(CONFIG, self.draft(self.baseline()))
        self.assertEqual([req.get_method() for req in opener.requests], ["GET", "GET"])

    def test_rename_system_binary_and_invalid_body_are_refused_before_network(self):
        original = self.baseline()
        cases = [
            {**self.draft(original), "title": "Renamed"},
            self.draft({**original, "title": "$:/System"}),
            self.draft({**original, "type": "image/png", "text": ""}),
            {**self.draft(original), "type": "image/png"},
            {**self.draft(original), "text": ["not text"]},
            {**self.draft(original), "tags": "[[unfinished"},
        ]
        for draft in cases:
            with self.subTest(draft=draft):
                with patch("tiddlywiki.urllib.request.build_opener") as build:
                    with self.assertRaises(tiddlywiki.WikiError):
                        tiddlywiki.update(CONFIG, draft)
                    build.assert_not_called()

    def test_readonly_anonymous_and_fresh_binary_are_refused_without_put(self):
        original = self.baseline()
        for responses in (
            [{"anonymous": False, "read_only": True}],
            [{"anonymous": True}],
            [{"anonymous": False}, {**original, "type": "image/png", "text": "base64"}],
            [{"anonymous": False}, {**original, "text": {"invalid": "body"}}],
            [{"anonymous": False}, {**original, "title": "Wrong title"}],
        ):
            with self.subTest(responses=responses):
                opener = FakeOpener(responses)
                with patch("tiddlywiki.urllib.request.build_opener", return_value=opener):
                    with self.assertRaises(tiddlywiki.WikiError):
                        tiddlywiki.update(CONFIG, self.draft(original))
                self.assertTrue(all(req.get_method() == "GET" for req in opener.requests))

    def test_update_network_failure_does_not_expose_private_diagnostics(self):
        original = self.baseline()
        for failure in (
            tiddlywiki.urllib.error.URLError("Private server stack test-secret"),
            tiddlywiki.urllib.error.HTTPError("https://private.invalid", 500, "Private server stack", {}, None),
        ):
            with self.subTest(failure=failure):
                opener = FakeOpener([{"anonymous": False}, original, failure])
                stdout = io.StringIO()
                with patch("tiddlywiki.urllib.request.build_opener", return_value=opener), \
                        patch("builtins.open", return_value=io.StringIO(json.dumps(CONFIG))), \
                        patch("sys.argv", ["tiddlywiki.py", "update"]), \
                        patch("sys.stdin", io.StringIO(json.dumps(self.draft(original)) + "\n")), \
                        patch("sys.stdout", stdout):
                    tiddlywiki.main()
                result = json.loads(stdout.getvalue())
                self.assertFalse(result["ok"])
                for secret in ("Private server stack", "private.invalid", CONFIG["password"], CONFIG["username"]):
                    self.assertNotIn(secret, result["error"])
                self.assertEqual([req.get_method() for req in opener.requests], ["GET", "GET", "PUT"])


class PreviewTests(unittest.TestCase):
    def test_offline_cli_renders_untitled_markdown_without_config_or_http(self):
        for content_type in ("text/x-markdown", "text/markdown", "Text/Markdown; charset=UTF-8"):
            with self.subTest(content_type=content_type):
                draft = {
                    "title": "", "type": content_type, "tags": "[[draft tag]]",
                    "text": "# Draft heading\n\n**Fresh draft** and [Link](https://remote.invalid)\n\n"
                            '<img src="https://remote.invalid/pic" onerror="active()">',
                    "context": [{"title": "Omarchy Markdown preview", "text": "Cached content",
                                 "type": "text/markdown", "tags": []}],
                }
                stdout = io.StringIO()
                with patch("builtins.open", side_effect=AssertionError("Private config opened")), \
                        patch("tiddlywiki.urllib.request.build_opener", side_effect=AssertionError("HTTP attempted")), \
                        patch("sys.argv", ["tiddlywiki.py", "preview"]), \
                        patch("sys.stdin", io.StringIO(json.dumps(draft) + "\n")), \
                        patch("sys.stdout", stdout):
                    tiddlywiki.main()
                result = json.loads(stdout.getvalue())
                self.assertTrue(result["ok"], result)
                for content in ("<h1>Draft heading</h1>", "<strong>Fresh draft</strong>", "Link"):
                    self.assertIn(content, result["html"])
                for excluded in ("Cached content", "remote.invalid", "src=", "href=", "onerror", "<img"):
                    self.assertNotIn(excluded, result["html"])

    def test_preview_refuses_nonmarkdown_system_and_invalid_context(self):
        for change in ({"type": "text/plain"}, {"type": "image/png"}, {"title": "$:/System"},
                       {"context": {}}, {"text": []}, {"tags": "[[unfinished"}):
            with self.subTest(change=change):
                draft = {"title": "Draft", "text": "**Body**", "type": "text/markdown", "tags": "", **change}
                with self.assertRaises(tiddlywiki.WikiError):
                    tiddlywiki.preview(draft)


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
        self.assertFalse(result["editable"])
        self.assertEqual(result["tiddler"]["text"], "")
        self.assertIn("no static text preview", result["html"])
        for excluded in ("base64", "payload", "src=", "<img", "Photo title"):
            self.assertNotIn(excluded, result["html"])


if __name__ == "__main__":
    unittest.main()
