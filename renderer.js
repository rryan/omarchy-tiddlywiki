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

        function addDataTiddler(fields) {
            const type = fields.type;
            if (typeof type === "string") {
                const mime = type.split(";", 1)[0].trim().toLowerCase();
                if (mime.startsWith("image/")) {
                    fields.type = mime;
                }
                // Select the trusted MIME parser without changing source metadata.
                if (mime !== type && Object.prototype.hasOwnProperty.call(tw.Wiki.parsers, mime)) {
                    tw.Wiki.parsers[type] = tw.Wiki.parsers[mime];
                }
            }
            tw.wiki.addTiddler(new tw.Tiddler(fields));
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
                addDataTiddler(fields);
            }
        }
        // Exact title lookup uses a variable, not a filter expression or URL.
        // The fresh selected tiddler wins over any cached contextual copy.
        addDataTiddler(target);
        // Discover through the trusted widgets/parsers, not source regexes: this
        // follows nested transclusions, filters and Markdown's decoded #titles.
        const missingImages = new Set();
        const imageTypes = new Set(["image/png", "image/jpeg", "image/jpg",
            "image/gif", "image/webp", "image/svg+xml"]);
        function noteImage(title, allowUnknown) {
            if (typeof title !== "string" || !title || title.startsWith("$:/")) {
                return;
            }
            const tiddler = tw.wiki.getTiddler(title);
            if (tiddler) {
                if (imageTypes.has(tiddler.fields.type) && !tiddler.fields.text
                        && !tiddler.fields._canonical_uri) {
                    missingImages.add(title);
                }
            } else if (allowUnknown && !/^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(title)) {
                missingImages.add(title);
            }
        }
        const ImageWidget = tw.modules.execute("$:/core/modules/widgets/image.js").image;
        const executeImage = ImageWidget.prototype.execute;
        ImageWidget.prototype.execute = function() {
            executeImage.call(this);
            // Markdown normalizes bare destinations (including bookmark screenshot
            // titles) into percent-encoded URIs. Exact titles win so literal "%20"
            // names remain distinct; decode only to an existing image tiddler.
            if (typeof this.imageSource === "string" && !tw.wiki.getTiddler(this.imageSource)) {
                const decoded = tw.utils.decodeURIComponentSafe(this.imageSource);
                const image = tw.wiki.getTiddler(decoded);
                if (image && imageTypes.has(image.fields.type)) {
                    this.imageSource = decoded;
                }
            }
            noteImage(this.imageSource, true);
        };
        const parseTextReference = tw.wiki.parseTextReference;
        tw.wiki.parseTextReference = function(title, field, index, options) {
            if ((!field || field === "text") && !index) {
                noteImage(title, false);
            }
            return parseTextReference.call(this, title, field, index, options);
        };
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
        return {ok: true, html, missingImages: [...missingImages]};
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
