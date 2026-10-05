# TiddlyWiki for Omarchy

Native Quickshell app with one main window for search, view, creation, and editing.
Create with **Super+Shift+P**, the bar's pencil button, or:

```sh
omarchy-shell shell summon rryan.tiddlywiki '{}'
```

Title and body come first, followed by tags and editable content type
(default `text/x-markdown`). Tab moves from title to body, then tags.
Tags use TiddlyWiki list syntax: `post [[multi word tag]]`.
**Ctrl+Enter** and **Save** both save and replace the editor with the saved
tiddler's view in the same window. Errors retain the draft. **Back/Escape**
from editing returns to the view; from creation it hides the app. Creation
and editing drafts are retained independently until saved or the shell reloads.
Switching away from a dirty edit never silently discards it.

### Live Markdown preview

A separate preview window opens automatically for `text/x-markdown` or
`text/markdown`, including MIME parameters and case variants. It updates
200 ms after typing pauses, without moving typing focus out of the editor.
The preview uses the same trusted local renderer and cached transclusion
context as the view; preview rendering itself does not access credentials
or make HTTP requests. Leaving the editor or choosing a non-Markdown type
closes it. Cancelled preview requests terminate and reap their renderer child.

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
- **/** or **Shift+Tab** from the results returns to the query without changing it.
- Selecting a result replaces the entire search pane with its view.
- The top-left **Back arrow** or **Escape** restores the query, selection,
  and results viewport. Escape from search hides the app.
- **e** or **Edit** in view opens the existing tiddler for editing.
  Titles are immutable; read-only accounts and non-text attachments cannot edit.

Editable inputs (query, title, body, tags, and content type) use Emacs-style bindings:

| Keys | Action |
| --- | --- |
| Ctrl+A / Ctrl+E | Beginning / end of the current logical line (not Select All) |
| Ctrl+B / Ctrl+F | Previous / next character |
| Alt+B / Alt+F | Previous / next word |
| Ctrl+P / Ctrl+N | Previous / next visual line in the body, retaining the horizontal position; no-op in single-line inputs |
| Ctrl+H / Ctrl+D | Delete previous / next character |
| Ctrl+K | Kill to line end, or kill the newline when already at line end |
| Ctrl+U | Kill from line beginning to the cursor |
| Ctrl+W / Alt+Backspace | Kill previous word, or the selected region |
| Alt+D | Kill next word, or the selected region |
| Ctrl+Y | Yank the latest kill, replacing any selection |
| Alt+Y | Immediately after yanking, cycle through earlier kills |

The 32-entry kill ring is shared across these inputs and stays in memory until
the shell restarts; it does not modify the system clipboard. Consecutive kills
in one input combine, with backward kills prepended. Other keyboard commands
end the sequence. Character movement/deletion preserves UTF-16 surrogate pairs.
Word movement treats whitespace and common punctuation as separators.
Read-only titles still allow movement but cannot be changed by deletion or yank.
Normal typing, clipboard shortcuts, Tab navigation, query arrows, and Ctrl+Enter
save remain available. This is text-editing support, not a full Emacs emulator.

The view is selectable and renders only the freshly fetched JSON tiddler body
locally using pinned TiddlyWiki 5.3.6 core and
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
The project `.npmrc` disables dependency command symlinks: Omarchy rejects
symlinks inside plugin folders, and the renderer loads TiddlyWiki as a library.

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

For a centered floating main window and a preview near the top-right corner,
use these rules in `~/.config/hypr/hyprland.lua`:

```lua
o.window({ class = "^org\\.quickshell$", title = "^TiddlyWiki$" }, {
  float = true,
  center = true,
  size = { 820, 680 },
})
o.window({ class = "^org\\.quickshell$", title = "^Markdown preview — TiddlyWiki$" }, {
  float = true,
  size = { 720, 620 },
  move = { "monitor_w-window_w-24", "40" },
  no_initial_focus = true,
})
```

Then run `hyprctl reload` and `hyprctl configerrors`.

## Save safety

Creation authenticates through `/status`, checks that the title does not
exist, and PUTs exactly one tiddler with TiddlyWiki's `X-Requested-With`
header and `If-None-Match: *`. Existing titles are never intentionally
overwritten by creation; `$:/` system titles are refused in both modes.
No delete, bulk write, automatic retry, or background posting.

Editing fetches the current fields again and compares them with the complete
snapshot opened in the editor before PUT. Already-observed changes or deletion
stop the save and retain the draft. Unedited custom fields, creator, and
creation timestamp survive updates. Returning to the view fetches fresh fields;
reopening a changed tiddler requires confirmation before discarding its retained edit.
Cancelling a same-tiddler reload resumes the retained edit without rebasing
it, so copying a draft remains possible without silently overwriting external changes.

TiddlyWiki 5.3.6 does not provide atomic compare-and-swap on these PUT routes.
A writer between the check and PUT can still be overwritten, or a concurrent
deletion can be undone by an update. Creation's conditional header may also
be unenforced. Choose distinct titles and avoid concurrent edits. After any
ambiguous save failure, check the wiki before retrying.

The wiki needs the Markdown plugin to render `text/x-markdown` posts.
Save smoke checks used a local server. A desktop-input smoke interaction
accidentally created one live test tiddler; that exact tiddler was removed
and its absence confirmed by HTTP 404. No existing posts were modified.
