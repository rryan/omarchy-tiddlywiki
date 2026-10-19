#!/usr/bin/env python3
"""Create, update, search, read, and locally preview tiddlers; JSON stdin/stdout."""
import base64
import datetime
import json
import html
from html.parser import HTMLParser
import os
import re
import shutil
import sqlite3
import signal
import stat
import tempfile
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


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


def validate_connection(config, require_password=True):
    """Validate local connection fields without contacting the wiki."""
    if not isinstance(config, dict):
        raise WikiError("Invalid connection settings.")
    url = config.get("url")
    username = config.get("username")
    password = config.get("password", "")
    if not isinstance(url, str) or not url or any(c.isspace() or ord(c) < 32 for c in url):
        raise WikiError("Enter a valid wiki URL.")
    try:
        parts = urllib.parse.urlsplit(url)
        parts.port
    except ValueError:
        raise WikiError("Enter a valid wiki URL.") from None
    if parts.scheme != "https" and not (
        parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost", "::1")
    ):
        raise WikiError("Use HTTPS for the wiki URL.")
    if not parts.hostname or "@" in parts.netloc or "?" in url or "#" in url or "\\" in url:
        raise WikiError("Configure a plain wiki URL; keep credentials in their separate fields.")
    if not isinstance(username, str) or not username or ":" in username or any(ord(c) < 32 for c in username):
        raise WikiError("Enter a valid HTTP Basic Authentication username.")
    if not isinstance(password, str) or (require_password and not password):
        raise WikiError("Enter an HTTP Basic Authentication password.")
    base = urllib.parse.urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), "", ""))
    return base, username, password


def load_settings(path):
    """Read only regular configuration files, without following symlinks."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None, None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise WikiError("The settings file must be a regular file.")
        with os.fdopen(fd, encoding="utf-8") as source:
            fd = None
            config = json.load(source)
        validate_connection(config)
        return config, info
    finally:
        if fd is not None:
            os.close(fd)


def settings_read(path):
    config, _ = load_settings(path)
    if config is None:
        return {"ok": True, "url": "", "username": "", "hasPassword": False}
    url, username, password = validate_connection(config)
    return {"ok": True, "url": url, "username": username, "hasPassword": bool(password)}


def settings_save(path, draft):
    url, username, password = validate_connection(draft, require_password=False)
    config, original = load_settings(path)
    previous = validate_connection(config) if config is not None else None
    changed = previous is None or (url, username) != previous[:2]
    if not password:
        if changed:
            raise WikiError("Enter a password for the new connection.")
        password = previous[2]
    updated = {**(config or {}), "url": url, "username": username, "password": password}
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".tiddlywiki-", dir=directory)
        with os.fdopen(fd, "w", encoding="utf-8") as destination:
            os.fchmod(destination.fileno(), 0o600)
            json.dump(updated, destination)
            destination.write("\n")
            destination.flush()
            os.fsync(destination.fileno())
        try:
            current = os.lstat(path)
        except FileNotFoundError:
            current = None
        if (current is not None and not stat.S_ISREG(current.st_mode)) or (
            (original is None) != (current is None)
        ) or (original is not None and (original.st_dev, original.st_ino) != (current.st_dev, current.st_ino)):
            raise WikiError("The settings file changed; reopen settings before saving.")
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            os.unlink(temporary)
    return {"ok": True, "connectionChanged": changed}


def connect(config, write=False):
    """Return a redirect-refusing authenticated request helper and server status."""
    base, username, password = validate_connection(config)
    auth = base64.b64encode((username + ":" + password).encode()).decode()
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

IMAGE_TYPES = frozenset(("image/png", "image/jpeg", "image/jpg", "image/gif",
                         "image/webp", "image/svg+xml"))


def image_type(content_type):
    return content_type.split(";", 1)[0].strip().lower() in IMAGE_TYPES


def render_fields(raw):
    """Keep image bytes only for this render, never in the returned search/edit state."""
    fields = normalize_tiddler(raw)
    if image_type(fields["type"]) and isinstance(raw.get("text"), str):
        fields["text"] = raw["text"]
    return fields


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
        with request(base + "/tiddlers.json?exclude=bag,text") as response:
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


BROWSER_PROFILES = {
    "google-chrome": "google-chrome", "chromium": "chromium",
    "brave-browser": "BraveSoftware/Brave-Browser", "microsoft-edge": "microsoft-edge",
}
BROWSER_SUFFIX = re.compile(r" [-–] (Google Chrome|Chromium|Brave|Microsoft\u200b? Edge)$")


def run(command, data=None):
    return subprocess.run(command, input=data, capture_output=True, check=True, timeout=10).stdout


def history_url(browser_class, page_title):
    """Most recently visited URL with this exact title across the browser's profiles."""
    root = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
                        BROWSER_PROFILES.get(browser_class, browser_class))
    best = None
    if not os.path.isdir(root):
        return None
    with tempfile.TemporaryDirectory() as scratch:
        for profile in os.listdir(root):
            history = os.path.join(root, profile, "History")
            if not os.path.isfile(history):
                continue
            copy = os.path.join(scratch, profile.replace(" ", "_"))
            shutil.copyfile(history, copy)
            if os.path.isfile(history + "-wal"):
                shutil.copyfile(history + "-wal", copy + "-wal")
            try:
                db = sqlite3.connect(copy)
                row = db.execute("SELECT url, last_visit_time FROM urls WHERE title = ? "
                                 "ORDER BY last_visit_time DESC LIMIT 1", (page_title,)).fetchone()
                db.close()
            except sqlite3.Error:
                continue
            if row and (best is None or row[1] > best[1]):
                best = row
    return best[0] if best else None


def page_top(ppm, scale):
    """Physical row where page content starts, below the tab strip, toolbar and bookmark bar.

    Down the window's left edge, Chromium paints a solid tab-strip run, then a solid
    toolbar run (which includes the bookmark bar), then a thin separator above the page.
    """
    # Exactly one whitespace byte separates the header from pixels, which may start with whitespace.
    header = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", ppm)
    if not header:
        raise WikiError("Unexpected screenshot format.")
    width, height = int(header[1]), int(header[2])
    pixels = ppm[header.end():]
    column = max(1, round(3 * scale))
    runs = []
    for row in range(height // 3):
        offset = (row * width + column) * 3
        color = pixels[offset:offset + 3]
        if runs and max(abs(a - b) for a, b in zip(color, runs[-1][0])) <= 6:
            runs[-1][2] = row
        else:
            runs.append([color, row, row])
    solid = [run for run in runs if run[2] - run[1] >= 10 * scale]
    if len(solid) < 2 or solid[0][1] > 2 * scale:
        raise WikiError("Could not find the page area below the browser toolbar.")
    return solid[1][2] + 1 + round(scale)


def address_bar_url(address):
    """Copy the browser window's address bar, then restore the previous clipboard."""
    try:
        types = run(["wl-paste", "--list-types"]).decode().split()
        kind = types[0] if types else None
        saved = run(["wl-paste", "--no-newline", "--type", kind]) if kind else None
    except (subprocess.CalledProcessError, OSError, UnicodeDecodeError):
        kind = saved = None
    try:
        for mods, key in (("CTRL", "L"), ("CTRL", "C"), ("", "Escape")):
            run(["hyprctl", "dispatch", "hl.dsp.send_shortcut({mods='%s', key='%s', window='address:%s'})"
                 % (mods, key, address)])
            subprocess.run(["sleep", "0.15"])
        url = run(["wl-paste", "--no-newline", "--type", "text/plain"]).decode().strip()
    except (subprocess.CalledProcessError, OSError, UnicodeDecodeError):
        url = ""
    finally:
        if saved is not None:
            subprocess.run(["wl-copy", "--type", kind], input=saved)
    return url if re.match(r"[a-z][a-z0-9+.-]*://\S+$", url) else None


def capture_browser():
    window = json.loads(run(["hyprctl", "activewindow", "-j"]))
    browser_class = window.get("class", "") if isinstance(window, dict) else ""
    if browser_class not in BROWSER_PROFILES:
        raise WikiError("Focus a browser window before bookmarking.")
    page_title = BROWSER_SUFFIX.sub("", window.get("title", "")).strip()
    if not page_title:
        raise WikiError("The browser tab has no title.")
    (x, y), (w, h) = window["at"], window["size"]
    # Screenshot before any address-bar fallback, whose omnibox dropdown would cover the page.
    if window.get("fullscreen") != 2:
        # Only the page: browser chrome would leak open tabs and bookmarks. (2 = real fullscreen; 1 = maximized.)
        ppm = run(["grim", "-g", f"{x},{y} {w}x{h}", "-t", "ppm", "-"])
        scale = int(ppm.split(maxsplit=3)[1]) / w
        top = -(-page_top(ppm, scale) // scale)
        y, h = y + int(top), h - int(top)
    png = run(["grim", "-g", f"{x},{y} {w}x{h}", "-t", "png", "-"])
    url = history_url(browser_class, page_title) or address_bar_url(window["address"])
    if not url:
        raise WikiError("Could not determine the browser tab's URL.")
    return page_title, url, png


def bookmark(config, capture=capture_browser):
    """Save the focused browser tab as a Markdown Bookmark tiddler plus a PNG screenshot tiddler.

    Returns a prepared edit session for the new bookmark so notes can be added immediately.
    """
    page_title, url, png = capture()
    request, status, recipe = connect(config, write=True)
    base = "/recipes/" + urllib.parse.quote(recipe, safe="")
    with request(base + "/tiddlers.json?exclude=bag,text") as response:
        tiddlers = json.load(response)
    if not isinstance(tiddlers, list):
        raise WikiError("The wiki returned an invalid search index.")
    titles = {normalize_tiddler(tiddler)["title"] for tiddler in tiddlers}
    stem = "Bookmark: " + page_title.replace("[[", "[").replace("]]", "]").replace("|", "-")
    title, number = stem, 1
    while title in titles or title + ".png" in titles:
        number += 1
        title = f"{stem} ({number})"
    image = title + ".png"
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S%f")[:17]
    user = status.get("username", config["username"])
    stamp = {"created": now, "modified": now, "creator": user, "modifier": user}
    # A bare tiddler title as the image destination transcludes the image tiddler in the wiki's
    # Markdown plugin; percent-encode only titles that can't sit inside <...>.
    target = f"<{image}>" if not re.search(r"[<>\n]", image) else urllib.parse.quote(image, safe="")
    text = f"<{url}>\n\n![Screenshot]({target})\n\n"
    for tiddler in (
        {"title": image, "type": "image/png", "tags": [], "text": base64.b64encode(png).decode(), **stamp},
        {"title": title, "type": "text/x-markdown", "tags": ["Bookmark"], "url": url,
         "screenshot": image, "text": text, **stamp},
    ):
        path = base + "/tiddlers/" + urllib.parse.quote(tiddler["title"], safe="")
        with request(path, "PUT", json.dumps(tiddler, ensure_ascii=False).encode(),
                     {"Content-Type": "application/json", "If-None-Match": "*"}) as response:
            if response.status not in (200, 201, 204):
                raise WikiError("Unexpected save response. Check the wiki before trying again.")
    # The editor's conflict check compares against the server's copy, revision included.
    with request(path) as response:
        fields = normalize_tiddler(json.load(response))
    if fields["title"] != title:
        raise WikiError("The wiki returned a different tiddler.")
    local = datetime.datetime.now()
    return {"ok": True, "kind": "bookmark", "mode": "edit", "date": f"{local.year}/{local.month}/{local.day}",
            "title": title, "url": url, "fields": fields, "tags": fields["tags"]}


def safe_svg(data):
    """An inert SVG subset: no styles, links, embedded content, scripts or animation."""
    if b"<!" in data or b"\x00" in data:
        return None
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, ValueError):
        return None
    namespace = "{http://www.w3.org/2000/svg}"
    elements = frozenset(("svg", "g", "defs", "path", "rect", "circle", "ellipse",
                          "line", "polyline", "polygon", "text", "tspan", "title", "desc",
                          "linearGradient", "radialGradient", "stop", "clipPath"))
    attributes = frozenset((
        "id", "viewBox", "preserveAspectRatio", "x", "y", "x1", "y1", "x2", "y2",
        "cx", "cy", "r", "rx", "ry", "width", "height", "d", "points", "transform",
        "fill", "fill-rule", "fill-opacity", "stroke", "stroke-width", "stroke-opacity",
        "stroke-linecap", "stroke-linejoin", "stroke-miterlimit", "stroke-dasharray",
        "stroke-dashoffset", "opacity", "clip-path", "clip-rule", "clipPathUnits",
        "gradientUnits", "gradientTransform", "offset", "stop-color", "stop-opacity",
        "fx", "fy", "fr", "spreadMethod", "font-family", "font-size", "font-weight",
        "font-style", "text-anchor", "dominant-baseline", "dx", "dy", "rotate",
    ))

    def local_name(tag):
        return tag[len(namespace):] if tag.startswith(namespace) else tag

    if local_name(root.tag) != "svg":
        return None

    def clean(node):
        node.tag = local_name(node.tag)
        for name, value in list(node.attrib.items()):
            if (name not in attributes or ("url" in value.lower()
                    and not re.fullmatch(r"url\(\s*#[A-Za-z_][\w.-]*\s*\)", value))):
                del node.attrib[name]
        for child in list(node):
            if local_name(child.tag) not in elements:
                node.remove(child)
            else:
                clean(child)

    clean(root)
    root.set("xmlns", "http://www.w3.org/2000/svg")
    return ET.tostring(root, encoding="utf-8")


def safe_image_source(source):
    """Canonicalize embedded image bytes; never let Qt resolve an arbitrary URL."""
    if not isinstance(source, str):
        return None
    match = re.fullmatch(r"data:(image/(?:png|jpeg|jpg|gif|webp|svg\+xml))(;base64)?,(.*)",
                         source, re.DOTALL)
    if not match:
        return None
    mime, encoded, payload = match.groups()
    try:
        if encoded:
            data = base64.b64decode(re.sub(r"\s+", "", payload), validate=True)
        elif mime == "image/svg+xml":
            data = urllib.parse.unquote_to_bytes(payload)
        else:
            return None
    except (ValueError, UnicodeError):
        return None
    if mime == "image/svg+xml":
        data = safe_svg(data)
        if data is None:
            return None
    elif not (
        (mime == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n"))
        or (mime in ("image/jpeg", "image/jpg") and data.startswith(b"\xff\xd8\xff"))
        or (mime == "image/gif" and data.startswith((b"GIF87a", b"GIF89a")))
        or (mime == "image/webp" and data.startswith(b"RIFF") and data[8:12] == b"WEBP")
    ):
        return None
    if mime == "image/jpg":
        mime = "image/jpeg"
    return "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")


class StaticRichText(HTMLParser):
    """Allow static Qt formatting and inert embedded images, never remote resources."""
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
        elif tag == "img":
            attributes = dict(attrs)
            source = safe_image_source(attributes.get("src"))
            if source:
                safe = ['src="' + source + '"']
                for name in ("width", "height"):
                    value = attributes.get(name) or ""
                    if re.fullmatch(r"(?:[1-9]\d{0,5})(?:\.\d{1,6})?", value):
                        safe.append(name + '="' + value + '"')
                if attributes.get("alt"):
                    safe.append('alt="' + html.escape(attributes["alt"], quote=True) + '"')
                self.fragments.append("<img " + " ".join(safe) + ">")
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


def render_once(fields, context):
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
    missing = result.get("missingImages", [])
    if not isinstance(missing, list) or any(not isinstance(title, str) for title in missing):
        raise WikiError("The local tiddler renderer returned an invalid response.")
    return result


def render_locally(fields, context, load_images=None):
    result = render_once(fields, context)
    missing = list(dict.fromkeys(result.get("missingImages", [])))
    if missing and load_images is not None:
        images = load_images(missing)
        if images:
            # Fetch the whole discovered batch before starting a second engine,
            # regardless of how many images the note actually uses.
            result = render_once(fields, context + images)
    return result["html"]


def fetch_images(request, recipe, titles):
    images = []
    for title in titles:
        if not title or title.startswith("$:/"):
            continue
        path = ("/recipes/" + urllib.parse.quote(recipe, safe="") + "/tiddlers/"
                + urllib.parse.quote(title, safe=""))
        try:
            with request(path) as response:
                raw = json.load(response)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            error.close()
            continue
        fields = render_fields(raw)
        if fields["title"] != title:
            raise WikiError("The wiki returned a different image tiddler.")
        if image_type(fields["type"]) and not fields.get("_canonical_uri"):
            images.append(fields)
    return images


def preview_images(titles):
    # Ordinary previews never reach this function: only a renderer-discovered
    # missing image can open the private connection settings or contact the wiki.
    config_path = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
                               "omarchy", "tiddlywiki.json")
    with open(config_path) as source:
        config = json.load(source)
    request, _, recipe = connect(config)
    return fetch_images(request, recipe, titles)


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
        raw = json.load(response)
    fields = normalize_tiddler(raw)
    if fields["title"] != title:
        raise WikiError("The wiki returned a different tiddler.")
    markup = render_locally(render_fields(raw), draft.get("context", []),
                            lambda titles: fetch_images(request, recipe,
                                                        [item for item in titles if item != title]))
    rendered = sanitize_tiddler_html(markup)
    if (not is_text_type(fields["type"]) and "<img " not in rendered
            and not html.unescape(re.sub(r"<[^>]*>", "", rendered)).strip()):
        rendered = ("<p>This image has no supported embedded preview. External and canonical image URLs are not loaded.</p>"
                    if image_type(fields["type"]) else "<p>This non-text tiddler has no static text preview.</p>")
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
    return {"ok": True, "html": sanitize_tiddler_html(render_locally(fields, context, preview_images))}


def _cancel_render(signum, _frame):
    # Raising through subprocess.run kills and reaps its renderer child.
    raise SystemExit(128 + signum)


def main():
    action = sys.argv[1] if len(sys.argv) == 2 else "create" if len(sys.argv) == 1 else None
    try:
        if action not in ("create", "update", "index", "read", "preview", "prepare", "bookmark",
                          "settings-read", "settings-save"):
            raise WikiError("Use create, update, index, read, preview, prepare, bookmark, settings-read, or settings-save.")
        if action in ("read", "preview"):
            signal.signal(signal.SIGTERM, _cancel_render)
        # bookmark runs from a key binding with no stdin payload.
        draft = {} if action == "bookmark" else json.loads(sys.stdin.readline())
        if not isinstance(draft, dict):
            raise WikiError("Expected a JSON object.")
        if action == "preview":
            # Only missing image bodies may lazily open private settings/HTTP.
            result = preview(draft)
        else:
            config_path = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "omarchy", "tiddlywiki.json")
            if action == "settings-read":
                result = settings_read(config_path)
            elif action == "settings-save":
                result = settings_save(config_path, draft)
            else:
                with open(config_path) as source:
                    config = json.load(source)
            if action in ("settings-read", "settings-save"):
                pass
            elif action == "index":
                result = index(config)
            elif action == "read":
                result = read_tiddler(config, draft)
            elif action == "update":
                result = update(config, draft)
            elif action == "prepare":
                result = prepare(config, draft)
            elif action == "bookmark":
                result = bookmark(config)
            else:
                result = create(config, draft)
    except urllib.error.HTTPError as error:
        error.close()
        message = "Wiki returned HTTP %s. Check credentials and permissions." % error.code
        if action in ("create", "update", "bookmark"):
            message += " If saving had started, check the wiki before retrying."
        result = {"ok": False, "error": message}
    except (urllib.error.URLError, TimeoutError, OSError, subprocess.SubprocessError) as error:
        message = "Could not complete the request (%s)." % type(error).__name__
        if action in ("create", "update"):
            message += " Draft retained. Check the wiki before retrying a save."
        result = {"ok": False, "error": message}
    except WikiError as error:
        result = {"ok": False, "error": str(error)}
    except (ValueError, KeyError, TypeError, AttributeError):
        result = {"ok": False, "error": "Invalid configuration, input, or wiki response."}
    print(json.dumps(result), flush=True)
    if action == "bookmark":
        if result["ok"]:
            subprocess.run(["omarchy-shell", "shell", "summon", "rryan.tiddlywiki",
                            json.dumps({"mode": "bookmark", "prepared": result})])
        else:
            subprocess.run(["notify-send", "TiddlyWiki bookmark", result["error"]])


if __name__ == "__main__":
    main()
