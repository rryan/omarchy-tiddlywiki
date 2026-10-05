#!/usr/bin/env node
"use strict";

// One-shot renderer: stdin/stdout JSON only, no wiki folder, server, or commands.
const path = require("path");
const {Console} = require("console");
const BODY_TEMPLATE = "$:/core/ui/ViewTemplate/body/default";
const FAILURE = "Local TiddlyWiki rendering failed.";
const DEPENDENCY_FAILURE = "Local TiddlyWiki renderer dependencies are unavailable. Run npm ci in the plugin directory.";

function ordinaryFields(source) {
    if (!source || typeof source !== "object" || Array.isArray(source)
            || typeof source.title !== "string" || !source.title
            || source.title.startsWith("$:/")) {
        return null;
    }
    const fields = Object.create(null);
    for (const [name, value] of Object.entries(source)) {
        // Remote code is content, never a module or a dynamically loaded plugin.
        if (name === "module-type" || name === "plugin-type") {
            continue;
        }
        if (typeof value === "string") {
            fields[name] = value;
        } else if (Array.isArray(value) && value.every(item => typeof item === "string")) {
            fields[name] = value;
        }
    }
    return fields;
}

async function render(request) {
    const target = ordinaryFields(request && request.tiddler);
    if (!target || (request.context !== undefined && !Array.isArray(request.context))) {
        return {ok: false, error: "Invalid local rendering request."};
    }

    let createWiki;
    let packageRoot;
    try {
        // Resolve relative to this script, not the caller's wiki/current directory.
        const packageFile = require.resolve("tiddlywiki/package.json", {paths: [__dirname]});
        packageRoot = path.dirname(packageFile);
        if (require(packageFile).version !== "5.3.6") {
            return {ok: false, error: DEPENDENCY_FAILURE};
        }
        createWiki = require(path.join(packageRoot, "boot", "boot.js")).TiddlyWiki;
    } catch (_) {
        return {ok: false, error: DEPENDENCY_FAILURE};
    }

    // Keep engine diagnostics off the JSON protocol. The Python client captures
    // stderr and exposes only the controlled errors returned below.
    global.console = new Console({stdout: process.stderr, stderr: process.stderr});

    try {
        const tw = createWiki();
        // initStartup interprets an empty argv as --help and otherwise defaults
        // to process.cwd(). Supply an explicit trusted path, then select the
        // empty wiki context BEFORE any loading occurs.
        tw.boot.argv = [packageRoot];
        tw.utils.error = () => { throw new Error(FAILURE); };
        tw.boot.initStartup({bootPath: path.join(packageRoot, "boot")});
        tw.boot.wikiPath = null;
        tw.boot.argv = [];
        tw.boot.extraPlugins = [];
        // Static rendering needs module setup and startup, not command dispatch,
        // host-info collection, live plugin reloading, or startup navigation.
        tw.boot.disabledStartupModules = ["commands", "info", "plugins", "story"];
        tw.boot.loadStartup();

        // Load precisely the bundled Markdown plugin, never environment/plugin
        // search paths or remote plugin bodies. Core was loaded by loadStartup.
        const markdown = tw.loadPluginFolder(path.join(packageRoot, "plugins", "tiddlywiki", "markdown"));
        if (!markdown || markdown.title !== "$:/plugins/tiddlywiki/markdown") {
            return {ok: false, error: DEPENDENCY_FAILURE};
        }
        tw.wiki.addTiddler(markdown);
        await new Promise((resolve, reject) => {
            try {
                tw.boot.execStartup({callback: resolve});
            } catch (error) {
                reject(error);
            }
        });
        if (!tw.Wiki.parsers["text/markdown"] || !tw.Wiki.parsers["text/x-markdown"]
                || !tw.wiki.getTiddler(BODY_TEMPLATE)) {
            return {ok: false, error: DEPENDENCY_FAILURE};
        }

        // Protect executable bundled resources; ordinary shadow content such as
        // GettingStarted may legitimately be overridden by the remote wiki.
        const trustedTitles = new Set([...tw.wiki.allTitles(), ...tw.wiki.allShadowTitles()]
            .filter(title => {
                const tiddler = tw.wiki.getTiddler(title);
                return tiddler && (tiddler.fields["module-type"] || tiddler.fields["plugin-type"]);
            }));
        if (trustedTitles.has(target.title)) {
            return {ok: false, error: "Cannot render a protected local renderer module."};
        }
        for (const source of request.context || []) {
            const fields = ordinaryFields(source);
            if (fields && !trustedTitles.has(fields.title)) {
                tw.wiki.addTiddler(new tw.Tiddler(fields));
            }
        }
        // Exact title lookup uses a variable, not a filter expression or URL.
        // The fresh selected tiddler wins over any cached contextual copy.
        tw.wiki.addTiddler(new tw.Tiddler(target));
        // Use the trusted default body template directly, with the same global
        // macro scope and static variables as the bundled server HTML template.
        // No remote template field or tagged ViewTemplate cascade selects it.
        const widget = tw.wiki.makeTranscludeWidget(BODY_TEMPLATE, {
            importPageMacros: true,
            mode: "block",
            variables: {
                currentTiddler: target.title,
                "tv-config-static": "yes",
                "tv-wikilink-template": "$uri_encoded$"
            }
        });
        const container = tw.fakeDocument.createElement("div");
        widget.render(container, null);
        const html = '<div class="tc-tiddler-body">' + container.innerHTML + "</div>";
        tw.wiki.clearTiddlerEventQueue();
        return {ok: true, html};
    } catch (_) {
        return {ok: false, error: FAILURE};
    }
}

async function main() {
    let request;
    try {
        process.stdin.setEncoding("utf8");
        let input = "";
        for await (const chunk of process.stdin) {
            input += chunk;
        }
        request = JSON.parse(input);
    } catch (_) {
        process.stdout.write(JSON.stringify({ok: false, error: "Invalid local rendering request."}) + "\n");
        return;
    }
    process.stdout.write(JSON.stringify(await render(request)) + "\n");
}

main().catch(() => {
    process.stdout.write(JSON.stringify({ok: false, error: FAILURE}) + "\n");
});
