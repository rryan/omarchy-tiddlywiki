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

- **Down/Up** select the next/previous result even with the query focused.
  Focus stays in the query; ordinary **j/k** remain text input there.
- **Tab** focuses results, where **j/k** also select the next/previous result.
- **Enter** opens the selected result from either the query or results.
- **Shift+Tab** returns to the query.
- **Escape** closes the reader first, then the search window.

The reader is modal, selectable, and read-only. It fetches fresh JSON fields
and renders only the body locally using pinned TiddlyWiki 5.3.6 core and
Markdown support. Ordinary transclusions use the cached in-memory index;
the freshly fetched selected tiddler overrides its cached copy. Titles with
slashes, spaces, `@`, `%`, or Unicode do not need an HTML route or proxy change.
Its native header shows the title, a muted author and local date/time
separated by a dot, and individually spaced tag chips. Metadata and wrapping
tags scroll with the body, so many tags do not hide the content in a small window.

Static text formatting is retained; scripts, links, images, and embedded
interactive content are removed. Non-text attachment bodies are not searched
or displayed as base64; their titles remain searchable. Remote plugin/module
code and `$:/` system tiddlers are not imported into the local renderer:
server-specific plugins and system customizations may render differently or
be unavailable. The trusted body template excludes wiki and tiddler chrome.

Wheel/touchpad distance is amplified in both results and the reader:
2× pixel deltas and 192 pixels per full wheel notch. No extra animation or
easing is added; native touch flicks and text selection remain available.
In the reader, **Down/Up** scroll one line and **Page Down/Page Up** scroll
one viewport with a one-line overlap. These shortcuts use unmodified keys;
modified keys retain their normal control behavior.
Search and read use GET requests only, including for read-only wiki accounts.
Searching does not discard an unsaved editor draft.

## Install

Requires Omarchy's Quickshell shell with Qt 6.9+, Python 3 (standard library
only), and Node.js 18+ with npm for the local renderer.

```sh
omarchy plugin add https://github.com/rryan/omarchy-tiddlywiki.git --enable --yes
npm --prefix "${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/rryan.tiddlywiki" ci \
  --ignore-scripts --no-audit --no-fund
```

The plugin is placed in the right bar section; move it with
`omarchy bar move rryan.tiddlywiki --section right`.

Dependencies are pinned in `package-lock.json`; installation does not run
package scripts. After an update changes the lockfile, rerun `npm ci` in the
installed plugin directory. Restart the shell to reload updated QML:
`omarchy restart shell`. A shell restart discards unsaved editor drafts.

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
