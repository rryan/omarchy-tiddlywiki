#!/usr/bin/env python3
"""Create, search, and read tiddlers via authenticated API; JSON stdin/stdout."""
import base64
import datetime
import json
import html
from html.parser import HTMLParser
import os
import re
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


def index(config):
    request, _, recipe = connect(config)
    path = "/recipes/" + urllib.parse.quote(recipe, safe="") + "/tiddlers.json?exclude=bag"
    with request(path) as response:
        tiddlers = json.load(response)
    if not isinstance(tiddlers, list):
        raise WikiError("The wiki returned an invalid search index.")
    fields = [normalize_tiddler(tiddler) for tiddler in tiddlers]
    return {"ok": True, "tiddlers": [item for item in fields if not item["title"].startswith("$:/")]}


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


def read_tiddler(config, draft):
    title = draft.get("title")
    if not isinstance(title, str) or not title:
        raise WikiError("Choose a tiddler to read.")
    if title.startswith("$:/"):
        raise WikiError("This reader does not open $:/ system tiddlers.")
    request, _, recipe = connect(config)
    encoded = urllib.parse.quote(title, safe="")
    path = "/recipes/" + urllib.parse.quote(recipe, safe="") + "/tiddlers/" + encoded
    with request(path) as response:
        fields = normalize_tiddler(json.load(response))
    if fields["title"] != title:
        raise WikiError("The wiki returned a different tiddler.")
    with request("/" + encoded, extra={"Accept": "text/html"}) as response:
        markup = response.read().decode("utf-8")
    rendered = sanitize_html(markup)
    if not is_text_type(fields["type"]) and not html.unescape(re.sub(r"<[^>]*>", "", rendered)).strip():
        rendered = "<p>This non-text tiddler has no static text preview.</p>"
    return {"ok": True, "tiddler": fields, "html": rendered}


def main():
    action = sys.argv[1] if len(sys.argv) == 2 else "create" if len(sys.argv) == 1 else None
    try:
        if action not in ("create", "index", "read"):
            raise WikiError("Use no action to create, or use index or read.")
        config_path = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "omarchy", "tiddlywiki.json")
        with open(config_path) as source:
            config = json.load(source)
        draft = json.loads(sys.stdin.readline())
        if not isinstance(draft, dict):
            raise WikiError("Expected a JSON object.")
        result = index(config) if action == "index" else read_tiddler(config, draft) if action == "read" else create(config, draft)
    except urllib.error.HTTPError as error:
        message = "Wiki returned HTTP %s. Check credentials and permissions." % error.code
        if action == "create":
            message += " If saving had started, check the wiki before retrying."
        result = {"ok": False, "error": message}
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        message = "Could not complete the request (%s)." % type(error).__name__
        if action == "create":
            message += " Draft retained. Check the wiki before retrying a save."
        result = {"ok": False, "error": message}
    except WikiError as error:
        result = {"ok": False, "error": str(error)}
    except (ValueError, KeyError, TypeError, AttributeError):
        result = {"ok": False, "error": "Invalid configuration, input, or wiki response."}
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
