# TiddlyWiki for Omarchy

Native Quickshell tiddler editor, opened by the bar's pencil button or:

```sh
omarchy-shell shell summon rryan.tiddlywiki '{}'
```

Title, tags, body, and editable content type; default `text/x-markdown`.
Tags use TiddlyWiki list syntax: `post [[multi word tag]]`. Save with the
Save button or Ctrl+Enter. Escape/Close hides the editor without clearing
the draft. A successful save clears the fields for another post and shows
confirmation. Errors preserve the draft. Drafts do not survive shell reloads.

## Install

Requires Omarchy's Quickshell shell and Python 3 (standard library only).

```sh
omarchy plugin add /path/to/tw-quickshell --enable --yes
```

The source must be a committed Git repository. The plugin is placed in the
right bar section; move it with `omarchy bar move rryan.tiddlywiki --section right`.

Create `~/.config/omarchy/tiddlywiki.json` (or the same path beneath
`XDG_CONFIG_HOME`) with permissions **0600**:

```json
{
  "url": "https://your-wiki.example/self",
  "username": "your-user",
  "password": "your-password"
}
```

Credentials are not stored in the plugin checkout, QML, or command-line
arguments. Remote URLs must use HTTPS; redirects are refused to avoid
sending credentials to a different server. The URL is the wiki root,
without the browser's `#` fragment or embedded credentials.

For a shortcut, add an unused key to `~/.config/hypr/bindings.lua`:

```lua
o.bind("SUPER + SHIFT + P", "Create TiddlyWiki tiddler", "omarchy-shell shell summon rryan.tiddlywiki '{}'")
```

Then run `hyprctl reload` and `hyprctl configerrors`.

## Save safety

The client reads `/status` to authenticate and discover the recipe, checks
that the title does not exist, and PUTs exactly one tiddler with TiddlyWiki's
`X-Requested-With` header. Existing titles and `$:/` system titles are
refused. No delete, bulk write, automatic retry, or background posting.

The PUT includes `If-None-Match: *`, but TiddlyWiki servers may not enforce
conditional writes. The existence check is not an atomic create guarantee:
a concurrent writer creating the identical title between GET and PUT could
be overwritten. Choose distinct post titles. After an ambiguous network
failure, check the wiki before retrying.

The wiki needs the Markdown plugin to render `text/x-markdown` posts.
Installation verification used read-only live requests and local-server
save smoke checks; no test tiddlers were posted to the real wiki.
