#!/usr/bin/env python3
"""Create, update, search, read, and locally preview tiddlers; JSON stdin/stdout."""
import base64
import datetime
import json
import html
from html.parser import HTMLParser
import os
import re
import signal
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class WikiError(ValueError):
    """An intentionally user-facing error without server or credential details."""

def parse_tags(text):
    """TiddlyWiki list syntax: whitespace-separated tags, [[multi word tags]]."""
    tags = []
    remaining = text.strip()
    while remaining:
        if remaining.startswith("[["):
            end = remaining.find("]]", 2)
            if end < 0:
                raise WikiError("Close multi-word tags with ]].")
            tag, remaining = remaining[2:end], remaining[end + 2:]
            if remaining and not remaining[0].isspace():
                raise WikiError("Separate tags with spaces.")
        else:
            match = re.match(r"\S+", remaining)
            tag = match.group()
            remaining = remaining[len(tag):]
            if "[[" in tag or "]]" in tag:
                raise WikiError("Use [[multi word tag]] for tags containing spaces.")
        if tag and tag not in tags:
            tags.append(tag)
        remaining = remaining.lstrip()
    return tags


def create(config, draft):
    title = draft.get("title", "").strip()
    if not title:
        raise WikiError("Enter a title.")
    if title.startswith("$:/"):
        raise WikiError("This editor creates posts, not $:/ system tiddlers.")
    content_type = draft.get("type", "").strip()
    if not content_type:
        raise WikiError("Enter a content type.")
    tags = parse_tags(draft.get("tags", ""))
    request, status, recipe = connect(config, write=True)
    path = "/recipes/" + urllib.parse.quote(recipe, safe="") + "/tiddlers/" + urllib.parse.quote(title, safe="")
    try:
        with request(path):
            pass
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        error.close()
    else:
        raise WikiError("A tiddler with this title already exists. Choose a different title; nothing was overwritten.")
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S%f")[:17]
    tiddler = {"title": title, "tags": tags, "text": draft.get("text", ""), "type": content_type,
               "created": now, "modified": now, "creator": status.get("username", config["username"]),
               "modifier": status.get("username", config["username"])}
    with request(path, "PUT", json.dumps(tiddler, ensure_ascii=False).encode(),
                 {"Content-Type": "application/json", "If-None-Match": "*"}) as response:
        if response.status not in (200, 201, 204):
            raise WikiError("Unexpected save response. Check the wiki before trying again.")
    return {"ok": True, "title": title}


def connect(config, write=False):
    """Return a redirect-refusing authenticated request helper and server status."""
    base = config["url"].rstrip("/")
    parts = urllib.parse.urlsplit(base)
    if parts.scheme != "https" and not (
        parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost", "::1")
    ):
        raise WikiError("Use HTTPS for the wiki URL.")
    if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise WikiError("Configure a plain wiki URL; keep credentials in their separate fields.")
    auth = base64.b64encode((config["username"] + ":" + config["password"]).encode()).decode()
    headers = {"Authorization": "Basic " + auth, "Accept": "application/json", "X-Requested-With": "TiddlyWiki"}
    opener = urllib.request.build_opener(NoRedirect())

    def request(path, method="GET", data=None, extra=None):
        req = urllib.request.Request(base + path, data=data, method=method, headers={**headers, **(extra or {})})
        return opener.open(req, timeout=20)

    with request("/status") as response:
        status = json.load(response)
    if not isinstance(status, dict) or status.get("anonymous", True):
        raise WikiError("The wiki account is anonymous. Configure an authenticated account.")
    if write and status.get("read_only"):
        raise WikiError("The wiki account is read-only.")
    recipe = status.get("space", {}).get("recipe", "default")
    if not isinstance(recipe, str):
        raise WikiError("The wiki returned an invalid recipe.")
    return request, status, recipe


def is_text_type(content_type):
    mime = content_type.split(";", 1)[0].strip().lower()
    return mime.startswith("text/") or mime in (
        "application/json", "application/javascript", "application/xml", "application/x-tiddler"
    ) or (mime.startswith("application/") and mime.endswith(("+json", "+xml")))


def normalize_tiddler(tiddler):
    if not isinstance(tiddler, dict) or not isinstance(tiddler.get("title"), str):
        raise WikiError("The wiki returned invalid tiddler fields.")
    fields = dict(tiddler)
    content_type = fields.get("type", "text/vnd.tiddlywiki")
    if not isinstance(content_type, str):
        raise WikiError("The wiki returned an invalid content type.")
    fields["type"] = content_type
    tags = fields.get("tags", [])
    if isinstance(tags, str):
        tags = parse_tags(tags)
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise WikiError("The wiki returned invalid tags.")
    fields["tags"] = list(dict.fromkeys(tags))
    text = fields.get("text", "")
    fields["text"] = text if isinstance(text, str) and is_text_type(content_type) else ""
    return fields


def editable_body(draft):
    content_type = draft.get("type", "")
    text = draft.get("text", "")
    tags = draft.get("tags", "")
    if not isinstance(content_type, str) or not content_type.strip():
        raise WikiError("Enter a content type.")
    content_type = content_type.strip()
    if not is_text_type(content_type):
        raise WikiError("This editor only saves text tiddlers.")
    if not isinstance(text, str) or not isinstance(tags, str):
        raise WikiError("Expected text and tags as strings.")
    return {"text": text, "type": content_type, "tags": parse_tags(tags)}


def update(config, draft):
    original = normalize_tiddler(draft.get("original"))
    title = draft.get("title")
    if not isinstance(title, str) or not title:
        raise WikiError("Choose a tiddler to edit.")
    if title != original["title"]:
        raise WikiError("A tiddler's title cannot be changed while editing.")
    if title.startswith("$:/"):
        raise WikiError("This editor does not edit $:/ system tiddlers.")
    if not is_text_type(original["type"]):
        raise WikiError("This editor only edits text tiddlers.")
    body = editable_body(draft)
    request, status, recipe = connect(config, write=True)
    path = "/recipes/" + urllib.parse.quote(recipe, safe="") + "/tiddlers/" + urllib.parse.quote(title, safe="")
    try:
        with request(path) as response:
            raw_fields = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            error.close()
            raise WikiError("The tiddler no longer exists. Nothing was saved.") from None
        raise
    fields = normalize_tiddler(raw_fields)
    if fields["title"] != title:
        raise WikiError("The wiki returned a different tiddler. Nothing was saved.")
    if not is_text_type(fields["type"]) or not isinstance(raw_fields.get("text", ""), str):
        raise WikiError("This editor only edits text tiddlers.")
    if fields != original:
        raise WikiError("The tiddler changed since it was opened. Reopen it before editing; nothing was saved.")
    # TW 5.3.6 has no atomic compare-and-swap for this endpoint. This protects
    # against already-observed changes, not writes between this GET and PUT.
    fields.update(body)
    fields["modified"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S%f")[:17]
    fields["modifier"] = status.get("username", config["username"])
    with request(path, "PUT", json.dumps(fields, ensure_ascii=False).encode(),
                 {"Content-Type": "application/json"}) as response:
        if response.status not in (200, 201, 204):
            raise WikiError("Unexpected save response. Check the wiki before trying again.")
    return {"ok": True, "title": title}


def index(config):
    request, _, recipe = connect(config)
    path = "/recipes/" + urllib.parse.quote(recipe, safe="") + "/tiddlers.json?exclude=bag"
    with request(path) as response:
        tiddlers = json.load(response)
    if not isinstance(tiddlers, list):
        raise WikiError("The wiki returned an invalid search index.")
    fields = [normalize_tiddler(tiddler) for tiddler in tiddlers]
    return {"ok": True, "tiddlers": [item for item in fields if not item["title"].startswith("$:/")],
            "wikiUrl": config["url"].rstrip("/") + "/"}


def prepare(config, draft):
    """Prepare a journal editor session without writing anything to the wiki."""
    if not isinstance(draft, dict) or draft.get("kind") not in ("today", "quick-note"):
        raise WikiError("Choose today or quick-note to prepare.")
    kind = draft["kind"]
    tag = "Journal" if kind == "today" else "Note"
    now = datetime.datetime.now()
    date = f"{now.year}/{now.month}/{now.day}"
    request, _, recipe = connect(config, write=True)
    base = "/recipes/" + urllib.parse.quote(recipe, safe="")
    fields = None
    title = date
    if kind == "today":
        path = base + "/tiddlers/" + urllib.parse.quote(title, safe="")
        try:
            with request(path) as response:
                raw_fields = json.load(response)
        except urllib.error.HTTPError as error:
            error.close()
            if error.code != 404:
                raise
        else:
            fields = normalize_tiddler(raw_fields)
            if fields["title"] != title:
                raise WikiError("The wiki returned a different tiddler. Nothing was saved.")
            if not is_text_type(fields["type"]) or not isinstance(raw_fields.get("text", ""), str):
                raise WikiError("This editor only edits text tiddlers.")
    else:
        with request(base + "/tiddlers.json?exclude=bag") as response:
            tiddlers = json.load(response)
        if not isinstance(tiddlers, list):
            raise WikiError("The wiki returned an invalid search index.")
        titles = {normalize_tiddler(tiddler)["title"] for tiddler in tiddlers}
        number = 1
        while f"{date} Quick Note {number}" in titles:
            number += 1
        title = f"{date} Quick Note {number}"
    mode = "edit" if fields is not None else "create"
    if fields is None:
        fields = {"title": title, "text": "", "type": "text/x-markdown", "tags": [tag]}
    tags = list(dict.fromkeys([*fields["tags"], tag]))
    return {"ok": True, "kind": kind, "date": date, "mode": mode, "fields": fields, "tags": tags}


class StaticRichText(HTMLParser):
    """Allow only static Qt text formatting, never URLs or server attributes."""
    allowed = frozenset((
        "p", "div", "span", "br", "hr", "b", "strong", "i", "em", "u", "s",
        "small", "sub", "sup", "pre", "code", "blockquote", "ul", "ol", "li",
        "dl", "dt", "dd", "table", "thead", "tbody", "tfoot", "tr", "td", "th",
        "h1", "h2", "h3", "h4", "h5", "h6",
    ))
    blocked = frozenset((
        "head", "script", "style", "iframe", "object", "embed", "applet", "form",
        "button", "select", "textarea", "video", "audio", "picture", "svg", "math",
        "canvas", "template",
    ))
    void = frozenset(("br", "hr", "img", "input", "meta", "link", "source", "track", "embed", "area", "base", "wbr"))

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fragments = []
        self.suppressed = []
        self.open_tags = []

    def handle_starttag(self, tag, attrs):
        if self.suppressed:
            if tag not in self.void:
                self.suppressed.append(tag)
        elif tag in self.blocked:
            if tag not in self.void:
                self.suppressed.append(tag)
        elif tag in self.allowed:
            self.fragments.append("<" + tag + ">")
            if tag not in self.void:
                self.open_tags.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.void:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.suppressed:
            if tag in self.suppressed:
                del self.suppressed[len(self.suppressed) - 1 - self.suppressed[::-1].index(tag):]
        elif tag in self.open_tags:
            position = len(self.open_tags) - 1 - self.open_tags[::-1].index(tag)
            for opened in reversed(self.open_tags[position:]):
                self.fragments.append("</" + opened + ">")
            del self.open_tags[position:]

    def handle_data(self, data):
        if not self.suppressed:
            self.fragments.append(html.escape(data))

    def result(self):
        return "".join(self.fragments) + "".join("</" + tag + ">" for tag in reversed(self.open_tags))


def sanitize_html(markup):
    parser = StaticRichText()
    try:
        parser.feed(markup)
        parser.close()
    except AssertionError:
        raise WikiError("The wiki returned malformed rendered HTML.") from None
    return parser.result()


class TiddlerBody(HTMLParser):
    """Select the body boundary before forwarding content to the sanitizer."""
    void = StaticRichText.void | frozenset(("col", "param"))

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sanitizer = StaticRichText()
        self.stack = []
        self.blocked_depth = 0
        self.body_depth = None
        self.complete = False

    def handle_starttag(self, tag, attrs):
        if self.complete:
            return
        if self.body_depth is not None:
            self.sanitizer.handle_starttag(tag, attrs)
        elif tag == "div" and not self.blocked_depth and any(
            name == "class" and "tc-tiddler-body" in (value or "").split()
            for name, value in attrs
        ):
            self.body_depth = len(self.stack)
        if tag not in self.void:
            self.stack.append(tag)
            if tag in StaticRichText.blocked:
                self.blocked_depth += 1

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.void:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.complete or tag not in self.stack:
            return
        position = len(self.stack) - 1 - self.stack[::-1].index(tag)
        if self.body_depth is not None:
            if position <= self.body_depth:
                self.complete = True
            else:
                self.sanitizer.handle_endtag(tag)
        self.blocked_depth -= sum(opened in StaticRichText.blocked for opened in self.stack[position:])
        del self.stack[position:]

    def handle_data(self, data):
        if self.body_depth is not None and not self.complete:
            self.sanitizer.handle_data(data)

    def result(self):
        if not self.complete:
            raise WikiError("The wiki returned no complete rendered tiddler body.")
        return self.sanitizer.result()


def sanitize_tiddler_html(markup):
    parser = TiddlerBody()
    try:
        parser.feed(markup)
        parser.close()
    except AssertionError:
        raise WikiError("The wiki returned malformed rendered HTML.") from None
    return parser.result()


def render_locally(fields, context):
    renderer = os.path.join(os.path.dirname(os.path.abspath(__file__)), "renderer.js")
    try:
        process = subprocess.run(
            ["node", renderer],
            input=json.dumps({"tiddler": fields, "context": context}),
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
    except FileNotFoundError:
        raise WikiError("Local rendering requires Node.js. Install Node.js and the plugin dependencies.") from None
    except subprocess.TimeoutExpired:
        raise WikiError("Local tiddler rendering timed out.") from None
    except (OSError, UnicodeError):
        raise WikiError("Could not start the local tiddler renderer.") from None
    if process.returncode:
        raise WikiError("Local tiddler rendering failed. Check the plugin installation and dependencies.")
    try:
        result = json.loads(process.stdout)
    except (ValueError, TypeError):
        raise WikiError("The local tiddler renderer returned an invalid response.") from None
    if not isinstance(result, dict):
        raise WikiError("The local tiddler renderer returned an invalid response.")
    if result.get("ok") is not True:
        # Only the bundled renderer's controlled error is public; stderr is never forwarded.
        error = result.get("error")
        raise WikiError(error if isinstance(error, str) and error else "Local tiddler rendering failed.")
    if not isinstance(result.get("html"), str):
        raise WikiError("The local tiddler renderer returned an invalid response.")
    return result["html"]


def read_tiddler(config, draft):
    title = draft.get("title")
    if not isinstance(title, str) or not title:
        raise WikiError("Choose a tiddler to read.")
    if title.startswith("$:/"):
        raise WikiError("This reader does not open $:/ system tiddlers.")
    request, status, recipe = connect(config)
    encoded = urllib.parse.quote(title, safe="")
    path = "/recipes/" + urllib.parse.quote(recipe, safe="") + "/tiddlers/" + encoded
    with request(path) as response:
        fields = normalize_tiddler(json.load(response))
    if fields["title"] != title:
        raise WikiError("The wiki returned a different tiddler.")
    markup = render_locally(fields, draft.get("context", []))
    rendered = sanitize_tiddler_html(markup)
    if not is_text_type(fields["type"]) and not html.unescape(re.sub(r"<[^>]*>", "", rendered)).strip():
        rendered = "<p>This non-text tiddler has no static text preview.</p>"
    return {"ok": True, "tiddler": fields, "html": rendered,
            "editable": is_text_type(fields["type"]) and not bool(status.get("read_only")),
            "wikiUrl": config["url"].rstrip("/") + "/"}


def preview(draft):
    fields = editable_body(draft)
    if fields["type"].split(";", 1)[0].strip().lower() not in ("text/x-markdown", "text/markdown"):
        raise WikiError("Live preview requires a Markdown content type.")
    title = draft.get("title", "")
    context = draft.get("context", [])
    if not isinstance(title, str) or not isinstance(context, list):
        raise WikiError("Invalid local preview input.")
    if title.startswith("$:/"):
        raise WikiError("This editor does not preview $:/ system tiddlers.")
    if not title.strip():
        # Do not shadow a cached ordinary tiddler when previewing an untitled draft.
        titles = {item.get("title") for item in context
                  if isinstance(item, dict) and isinstance(item.get("title"), str)}
        title = "Omarchy Markdown preview"
        while title in titles:
            title += "_"
    fields["title"] = title
    return {"ok": True, "html": sanitize_tiddler_html(render_locally(fields, context))}


def _cancel_render(signum, _frame):
    # Raising through subprocess.run kills and reaps its renderer child.
    raise SystemExit(128 + signum)


def main():
    action = sys.argv[1] if len(sys.argv) == 2 else "create" if len(sys.argv) == 1 else None
    try:
        if action not in ("create", "update", "index", "read", "preview", "prepare"):
            raise WikiError("Use create, update, index, read, preview, or prepare.")
        if action in ("read", "preview"):
            signal.signal(signal.SIGTERM, _cancel_render)
        draft = json.loads(sys.stdin.readline())
        if not isinstance(draft, dict):
            raise WikiError("Expected a JSON object.")
        if action == "preview":
            # Offline drafts must never open the private configuration or HTTP.
            result = preview(draft)
        else:
            config_path = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "omarchy", "tiddlywiki.json")
            with open(config_path) as source:
                config = json.load(source)
            if action == "index":
                result = index(config)
            elif action == "read":
                result = read_tiddler(config, draft)
            elif action == "update":
                result = update(config, draft)
            elif action == "prepare":
                result = prepare(config, draft)
            else:
                result = create(config, draft)
    except urllib.error.HTTPError as error:
        error.close()
        message = "Wiki returned HTTP %s. Check credentials and permissions." % error.code
        if action in ("create", "update"):
            message += " If saving had started, check the wiki before retrying."
        result = {"ok": False, "error": message}
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        message = "Could not complete the request (%s)." % type(error).__name__
        if action in ("create", "update"):
            message += " Draft retained. Check the wiki before retrying a save."
        result = {"ok": False, "error": message}
    except WikiError as error:
        result = {"ok": False, "error": str(error)}
    except (ValueError, KeyError, TypeError, AttributeError):
        result = {"ok": False, "error": "Invalid configuration, input, or wiki response."}
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
