# [TiddlyWiki](https://tiddlywiki.com/) for Omarchy

A native Omarchy window for searching, reading, creating, and editing your [TiddlyWiki](https://tiddlywiki.com/) notes, with an inline live Markdown preview. For people who want quick capture and keyboard-friendly access to an existing wiki without opening a browser for every note.

- Create a tiddler from the bar's pencil button.
- Search titles and note text, read results, and edit existing notes.
- Open today's journal or capture automatically numbered quick notes.
- Keep separate unsaved drafts while moving between tasks.
- Use Emacs-style text editing, or open a note in the full wiki in your browser.

## Requirements

**Only [TiddlyWiki](https://tiddlywiki.com/) hosted on Node.js is supported.** A standalone HTML file, a browser-only wiki, or another hosting arrangement is not supported. Follow the official [Installing on Node.js guide](https://tiddlywiki.com/static/Installing%2520TiddlyWiki%2520on%2520Node.js.html) to set up your wiki first.

You also need:

- Omarchy's Quickshell shell with Qt 6.9 or newer.
- Python 3, Node.js 18 or newer, and npm.
- A reachable wiki and an HTTP Basic Authentication account. Use an account with write permission to create or edit notes; read-only accounts can search and read.
- Markdown support enabled in your wiki if you want Markdown notes to display correctly in the browser.

## Install

Install missing dependencies on Omarchy:

```sh
omarchy pkg add python nodejs npm
```

Install and enable the plugin, then install its dependencies:

```sh
omarchy plugin add https://github.com/rryan/omarchy-tiddlywiki.git --enable --yes
(
  cd "${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/rryan.tiddlywiki"
  npm ci --ignore-scripts --no-audit --no-fund
)
```

The pencil button appears in the right section of the bar. To move it back there later:

```sh
omarchy bar move rryan.tiddlywiki --section right
```

### Connect your wiki

1. **Right-click the bar's pencil button** to open **Settings**. No keyboard shortcuts are required for this.
2. Enter the **Wiki URL**: your wiki's root address, including any hosting path, for example `https://your-wiki.example/notes`. Do not include a note's `#` fragment, a query string, or credentials in the URL. Use HTTPS for remote wikis; HTTP is allowed only for localhost.
3. Enter the **Username** and **Password** for your wiki's **HTTP Basic Authentication** account. These are the credentials configured for the Node.js host, not an unrelated wiki login or browser session.
4. Save the settings. Left-click the pencil to create a note.

An existing password is never displayed. Leave Password blank to keep it when the URL and username are unchanged. Supply a password when switching to a different URL or username.

Changing the connection discards this session's retained drafts after a successful save. If drafts exist, Settings asks you to confirm first. Cancel the confirmation to keep both the drafts and the settings form. A failed settings save leaves your entered values available for correction. Opening or editing Settings does not contact the wiki.

Connection settings are stored separately from the plugin in `${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/tiddlywiki.json`. Treat this file as private: it contains your account password.

### Optional keyboard shortcuts

These shortcuts are **not installed automatically**. Add the following to `~/.config/hypr/bindings.lua` if you want them. The `O` binding replaces the existing Obsidian shortcut; check for conflicts with your other custom bindings too.

```lua
o.bind("SUPER + SHIFT + P", "Create TiddlyWiki tiddler", "omarchy-shell shell summon rryan.tiddlywiki '{}'")
hl.unbind("SUPER + SHIFT + O") -- Previously Obsidian.
o.bind("SUPER + SHIFT + O", "Search TiddlyWiki tiddlers", "omarchy-shell shell summon rryan.tiddlywiki '{\"mode\":\"search\"}'")
o.bind("SUPER + SHIFT + T", "Today's TiddlyWiki journal", "omarchy-shell shell summon rryan.tiddlywiki '{\"mode\":\"today\"}'")
o.bind("SUPER + SHIFT + I", "TiddlyWiki quick note", "omarchy-shell shell summon rryan.tiddlywiki '{\"mode\":\"quick-note\"}'")
```

| Optional shortcut | Opens |
| --- | --- |
| Super+Shift+P | New tiddler |
| Super+Shift+O | Search |
| Super+Shift+T | Today's journal |
| Super+Shift+I | Quick note |

Without shortcuts, left-click the pencil to create, or run the corresponding `omarchy-shell shell summon` command above in a terminal to open search, journal, or quick note.

### Optional window rule

For a centered floating window with room for the editor and preview, add this to `~/.config/hypr/hyprland.lua`:

```lua
o.window({ class = "^org\\.quickshell$", title = "^TiddlyWiki$" }, {
  float = true,
  center = true,
  size = { 1200, 760 },
})
```

After changing shortcuts or window rules, apply and check your configuration:

```sh
hyprctl reload
hyprctl configerrors
```

## Create, journal, and capture

New notes start with a title, body, tags, and an editable content type. The default is Markdown (`text/x-markdown`). Tab moves from title to body, then tags. Separate multi-word tags with double brackets, for example `post [[multi word tag]]`.

**Today's journal** uses your local date as its title, such as `2026/10/5`. It opens that note if it already exists, or prepares a new Markdown note, and adds the **Journal** tag without removing existing tags. The body receives focus, with the cursor at the end.

**Quick note** prepares a Markdown note tagged **Note**, with a title such as `2026/10/5 Quick Note 1`. It chooses the lowest unused positive number for today. After saving, the next quick note gets another available number. The body is focused so you can type immediately.

Opening either mode does not save anything. Reopening a journal or quick-note mode restores its unsaved draft for that date, with the cursor at the end of the body.

### Preview

Markdown notes show the form on the left and a live preview on the right, in the same window. The preview updates shortly after you pause typing without taking focus away from the body. Choosing another content type hides the preview and gives the form the full width. References to other notes may take a moment to appear while the wiki loads.

### Save, back, and drafts

| Action | Result |
| --- | --- |
| Save or Ctrl+Enter in a new note, journal, or quick note | Saves successfully, then closes the window |
| Save or Ctrl+Enter when editing from a note's view | Saves successfully, then returns to that view |
| Back or Escape in an edit entered from a view | Returns to the view |
| Back or Escape in a view entered from search | Returns to the previous query, selection, and results position |
| Back or Escape in a directly opened creation, journal, or quick-note form | Closes the window, including on its loading or error page |
| Escape in search | Closes the window |

A failed save leaves the form and draft open. Closing a form or switching tasks retains its unsaved draft for this shell session; creation and existing-note drafts are kept separately. Searching does not discard an editor draft. If a note has changed since a retained draft was opened, reloading it asks before replacing that draft.

**Drafts are not saved to your wiki until you choose Save. Restarting or reloading the shell loses unsaved drafts.** Copy important unsaved text somewhere safe before updating or restarting. A confirmed connection change also clears retained drafts.

## Search, read, and edit

Search results update as you type. Exact titles and title prefixes rank first, followed by other title matches and matches in note text. Every query word must match the title or body. An empty query lists ordinary notes. Previously loaded results remain usable while they refresh, including when a refresh fails.

| Where | Key | Action |
| --- | --- | --- |
| Search query or results | Down / Up | Select next / previous result |
| Search query or results | Enter | Open selected result |
| Search query | Tab | Focus results |
| Results | j / k | Select next / previous result |
| Results | / or Shift+Tab | Return to query |
| Results | o | Open selected note in browser |
| Note view | e | Edit note |
| Note view | o | Open note in browser |
| Note view | Down / Up | Scroll one line |
| Note view | Page Down / Page Up | Scroll one page |

The view also provides **Edit** and **Back** buttons. Existing titles cannot be renamed here. Read-only accounts and non-text attachments cannot be edited. In text inputs, `j`, `k`, `/`, `e`, and `o` remain ordinary typing rather than navigation commands.

Opening a note with **o** opens the **full wiki** in your default browser. You may need to sign in separately in the browser.

### Emacs-style text editing

The search query and editor text fields support these basics alongside normal typing, clipboard shortcuts, Tab navigation, and Ctrl+Enter to save:

| Keys | Action |
| --- | --- |
| Ctrl+A / Ctrl+E | Beginning / end of current line, not Select All |
| Ctrl+B / Ctrl+F | Previous / next character |
| Alt+B / Alt+F | Previous / next word |
| Ctrl+P / Ctrl+N | Previous / next visual line in the body |
| Ctrl+H / Ctrl+D | Delete previous / next character |
| Ctrl+K | Kill to line end; kill the newline if already at line end |
| Ctrl+U | Kill from line beginning to cursor |
| Ctrl+W / Alt+Backspace | Kill previous word, or selected text |
| Alt+D | Kill next word, or selected text |
| Ctrl+Y | Yank the latest kill |
| Alt+Y | Immediately after a yank, cycle through earlier kills |

Killed text is shared between these inputs for the current shell session, separately from the system clipboard. Ctrl+P/Ctrl+N do nothing in single-line fields. This is convenient text editing, not a full Emacs environment.

## Limitations and save care

- This is a focused note window, not a replacement for the full [TiddlyWiki](https://tiddlywiki.com/) interface. Custom wiki displays, plugins, and interactive content may look different or be unavailable. Use **o** to see the full browser version.
- Non-text attachments can be found by title, but their contents are not shown or searched. Images and embedded interactive content are not displayed in the native view.
- System notes are not offered for ordinary search or editing. There is no delete or rename action.
- Creation refuses a title that already exists. Editing stops if it detects that the note changed or disappeared after you opened it, keeping your draft available.
- Avoid editing the same note simultaneously elsewhere: changes made at the exact moment of saving can still conflict. If a save reports an uncertain failure, check the wiki before trying again.

## Update

Save your work or copy drafts somewhere safe first: reloading the plugin or shell can lose unsaved drafts.

```sh
omarchy plugin update rryan.tiddlywiki
(
  cd "${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/rryan.tiddlywiki"
  npm ci --ignore-scripts --no-audit --no-fund
)
omarchy restart shell
```

The restart loads the updated plugin and **discards unsaved drafts**. Your saved notes and separate connection settings remain in place.

## Uninstall

1. Save any drafts you want to keep, then remove the plugin:

   ```sh
   omarchy plugin remove rryan.tiddlywiki
   ```

2. If you added the optional shortcuts, remove their four `o.bind` lines and the accompanying `hl.unbind("SUPER + SHIFT + O")` from `~/.config/hypr/bindings.lua`. Restore your previous `O` binding if you replaced it. Remove the optional window rule from `~/.config/hypr/hyprland.lua`, then run:

   ```sh
   hyprctl reload
   hyprctl configerrors
   ```

3. Optionally delete the private connection settings if you no longer need them:

   ```sh
   rm -- "${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/tiddlywiki.json"
   ```

   **This deletes the locally stored wiki URL, username, and password.** Keep them elsewhere if you plan to reinstall. Leaving the file in place retains those private settings.

Uninstalling does **not** remove your wiki, its hosting installation, or any saved tiddlers. Unsaved session drafts are not preserved by uninstalling.

## License

MIT License. See [LICENSE](LICENSE).
