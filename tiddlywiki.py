#!/usr/bin/env python3
"""Create tiddlers via TiddlyWiki's authenticated server API; JSON stdin/stdout."""
import base64
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def parse_tags(text):
    """TiddlyWiki list syntax: whitespace-separated tags, [[multi word tags]]."""
    tags = []
    remaining = text.strip()
    while remaining:
        if remaining.startswith("[["):
            end = remaining.find("]]", 2)
            if end < 0:
                raise ValueError("Close multi-word tags with ]].")
            tag, remaining = remaining[2:end], remaining[end + 2:]
            if remaining and not remaining[0].isspace():
                raise ValueError("Separate tags with spaces.")
        else:
            match = re.match(r"\S+", remaining)
            tag = match.group()
            remaining = remaining[len(tag):]
            if "[[" in tag or "]]" in tag:
                raise ValueError("Use [[multi word tag]] for tags containing spaces.")
        if tag and tag not in tags:
            tags.append(tag)
        remaining = remaining.lstrip()
    return tags


def create(config, draft):
    title = draft.get("title", "").strip()
    if not title:
        raise ValueError("Enter a title.")
    if title.startswith("$:/"):
        raise ValueError("This editor creates posts, not $:/ system tiddlers.")
    content_type = draft.get("type", "").strip()
    if not content_type:
        raise ValueError("Enter a content type.")
    tags = parse_tags(draft.get("tags", ""))
    base = config["url"].rstrip("/")
    url_parts = urllib.parse.urlsplit(base)
    if url_parts.scheme != "https" and not (
        url_parts.scheme == "http" and url_parts.hostname in ("127.0.0.1", "localhost", "::1")
    ):
        raise ValueError("Use HTTPS for the wiki URL.")
    if url_parts.username or url_parts.query or url_parts.fragment:
        raise ValueError("Configure a plain wiki URL; keep credentials in their separate fields.")
    auth = base64.b64encode((config["username"] + ":" + config["password"]).encode()).decode()
    headers = {"Authorization": "Basic " + auth, "Accept": "application/json", "X-Requested-With": "TiddlyWiki"}
    opener = urllib.request.build_opener(NoRedirect())

    def request(path, method="GET", data=None, extra=None):
        req = urllib.request.Request(base + path, data=data, method=method, headers={**headers, **(extra or {})})
        return opener.open(req, timeout=20)

    with request("/status") as response:
        status = json.load(response)
    if status.get("anonymous") or status.get("read_only"):
        raise ValueError("The wiki account is anonymous or read-only.")
    recipe = status.get("space", {}).get("recipe", "default")
    path = "/recipes/" + urllib.parse.quote(recipe, safe="") + "/tiddlers/" + urllib.parse.quote(title, safe="")
    try:
        with request(path):
            pass
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    else:
        raise ValueError("A tiddler with this title already exists. Choose a different title; nothing was overwritten.")
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S%f")[:17]
    tiddler = {"title": title, "tags": tags, "text": draft.get("text", ""), "type": content_type,
               "created": now, "modified": now, "creator": status.get("username", config["username"]),
               "modifier": status.get("username", config["username"])}
    with request(path, "PUT", json.dumps(tiddler, ensure_ascii=False).encode(),
                 {"Content-Type": "application/json", "If-None-Match": "*"}) as response:
        if response.status not in (200, 201, 204):
            raise ValueError("Unexpected save response. Check the wiki before trying again.")
    return {"ok": True, "title": title}


def main():
    try:
        config_path = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "omarchy", "tiddlywiki.json")
        with open(config_path) as source:
            config = json.load(source)
        result = create(config, json.loads(sys.stdin.readline()))
    except urllib.error.HTTPError as error:
        result = {"ok": False, "error": "Wiki returned HTTP %s. Check credentials and permissions. If saving had started, check the wiki before retrying." % error.code}
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        result = {"ok": False, "error": "Could not complete the request (%s). Draft retained. Check the wiki before retrying a save." % type(error).__name__}
    except (ValueError, KeyError, TypeError) as error:
        result = {"ok": False, "error": str(error)}
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
