# TiddlyWiki for Omarchy

Native Quickshell tiddler editor and read-only search. Create from the bar's pencil button or:

```sh
omarchy-shell shell summon rryan.tiddlywiki '{}'
```

Title and body come first, followed by tags and editable content type
(default `text/x-markdown`). Tab moves from title to body, then tags.
Tags use TiddlyWiki list syntax: `post [[multi word tag]]`.
Ctrl+Enter saves and dismisses the editor after success. The Save button
saves and keeps the editor open for another post. Errors keep the dialog
open and preserve the draft. Escape/Close hides the editor without clearing
the draft. Successful saves clear the fields; drafts do not survive shell reloads.

## Search and read

Open with Super+Shift+O (replaces Obsidian when the binding below is installed),
or summon directly:

```sh
omarchy-shell shell summon rryan.tiddlywiki '{"mode":"search"}'
```

Results update as you type. Exact titles and prefixes rank first, followed
by title substrings, acronyms/subsequences, and body-text matches. Every
query word must match a title or the body; an empty query lists all ordinary
tiddlers. The prepared index stays only in memory and is reused immediately
on reopening while a background request refreshes it. Results remain visible
while typing; a failed refresh keeps cached results searchable.

- **Tab** from the query focuses results. Ordinary **j/k** still type in the query.
- In results, **j/k** or **Down/Up** select the next/previous result.
- **Enter** opens the selection; from the query it opens the top result.
- **Shift+Tab** returns to the query.
- **Escape** closes the reader first, then the search window.

The reader is modal, selectable, and read-only. It fetches fresh fields and
only the server-rendered tiddler body, excluding the wiki title/subtitle and
duplicate tiddler chrome. Its native header shows the tiddler title, a muted
author and local date/time separated by a dot, and individually spaced tag
chips. Metadata and wrapping tags scroll with the body, so many tags do not
hide the content in a small window.

Static text formatting is retained; scripts, links, images, and embedded
interactive content are removed. Non-text attachment bodies are not searched
or displayed as base64; their titles remain searchable. The server's static
render must contain a `tc-tiddler-body` container; an absent or incomplete
container produces a reader error instead of displaying the entire wiki page.

Wheel/touchpad distance is amplified in both results and the reader:
2× pixel deltas and 192 pixels per full wheel notch. No extra animation or
easing is added; native touch flicks and text selection remain available.
Search and read use GET requests only, including for read-only wiki accounts.
Searching does not discard an unsaved editor draft.

## Install

Requires Omarchy's Quickshell shell with Qt 6.9+ and Python 3 (standard library only).

```sh
omarchy plugin add https://github.com/rryan/omarchy-tiddlywiki.git --enable --yes
```

The plugin is placed in the right bar section; move it with
`omarchy bar move rryan.tiddlywiki --section right`.

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

For creation and search shortcuts, add these to `~/.config/hypr/bindings.lua`:

```lua
o.bind("SUPER + SHIFT + P", "Create TiddlyWiki tiddler", "omarchy-shell shell summon rryan.tiddlywiki '{}'")
hl.unbind("SUPER + SHIFT + O") -- Previously Obsidian.
o.bind("SUPER + SHIFT + O", "Search TiddlyWiki tiddlers", "omarchy-shell shell summon rryan.tiddlywiki '{\"mode\":\"search\"}'")
```

For centered hovering windows that do not rearrange tiled windows, add
these rules to `~/.config/hypr/hyprland.lua`:

```lua
o.window({ class = "^org\\.quickshell$", title = "^Create tiddler — TiddlyWiki$" }, {
  float = true,
  center = true,
  size = { 780, 620 },
})
o.window({ class = "^org\\.quickshell$", title = "^Search tiddlers — TiddlyWiki$" }, {
  float = true,
  center = true,
  size = { 820, 680 },
})
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
Save smoke checks used a local server. A desktop-input smoke interaction
accidentally created one live test tiddler; that exact tiddler was removed
and its absence confirmed by HTTP 404. No existing posts were modified.
