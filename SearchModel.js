.pragma library

function folded(value) {
    return String(value || "").toLowerCase();
}

function tokens(query) {
    var value = folded(query).trim();
    return value ? value.split(/\s+/) : [];
}

function initials(title) {
    var result = "";
    for (var i = 0; i < title.length; ++i) {
        var current = title.charAt(i);
        var previous = i ? title.charAt(i - 1) : "";
        if (/[^\s\-_./]/.test(current) && (!i || /[\s\-_./]/.test(previous)
                || (/[a-z]/.test(previous) && /[A-Z]/.test(current))))
            result += current.toLowerCase();
    }
    return result;
}

// Lower scores are better; a negative score means the token is not a subsequence.
function subsequenceScore(title, token) {
    var cursor = 0;
    var first = -1;
    var last = -1;
    var boundaries = 0;
    for (var i = 0; i < token.length; ++i) {
        var at = title.indexOf(token.charAt(i), cursor);
        if (at < 0) return -1;
        if (first < 0) first = at;
        if (!at || /[\s\-_./]/.test(title.charAt(at - 1))) ++boundaries;
        last = at;
        cursor = at + 1;
    }
    return Math.max(0, (last - first + 1 - token.length) * 4 + first - boundaries);
}

// Title exact/prefix/substring/acronym/subsequence all outrank body-only tokens.
function titleScore(document, token) {
    var title = document.titleFolded;
    if (title === token) return 5000;
    if (title.indexOf(token) === 0) return 4000;
    var at = title.indexOf(token);
    if (at >= 0) return 3000 - Math.min(at, 500);
    if (document.initials.indexOf(token) >= 0) return 2500;
    var fuzzy = subsequenceScore(title, token);
    return fuzzy < 0 ? -1 : 2000 - Math.min(fuzzy, 1000);
}

function prepareIndex(tiddlers) {
    var documents = [];
    for (var i = 0; i < tiddlers.length; ++i) {
        var tiddler = tiddlers[i];
        if (!tiddler || typeof tiddler.title !== "string" || tiddler.title.indexOf("$:") === 0)
            continue;
        var body = String(tiddler.text || "");
        documents.push({title: tiddler.title, titleFolded: folded(tiddler.title),
            initials: initials(tiddler.title), body: body, bodyFolded: folded(body), fields: tiddler});
    }
    return documents;
}

function snippet(document, bodyTokens) {
    if (!bodyTokens.length) return "";
    var at = document.bodyFolded.indexOf(bodyTokens[0]);
    var start = Math.max(0, at - 55);
    var end = Math.min(document.body.length, at + 145);
    // Delegates also use Text.PlainText: wiki/HTML source cannot become markup.
    var text = document.body.slice(start, end).replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
    return (start ? "…" : "") + text + (end < document.body.length ? "…" : "");
}

function scoreDocument(document, queryTokens, phrase) {
    var score = 0;
    var bodyTokens = [];
    for (var i = 0; i < queryTokens.length; ++i) {
        var token = queryTokens[i];
        var title = titleScore(document, token);
        if (title >= 0) score += title;
        else if (document.bodyFolded.indexOf(token) >= 0) bodyTokens.push(token);
        else return null;
    }
    var rank = 3;
    if (!queryTokens.length) rank = 0;
    else if (bodyTokens.length) rank = 4;
    else if (document.titleFolded === phrase) rank = 0;
    else if (document.titleFolded.indexOf(phrase) === 0) rank = 1;
    else if (document.titleFolded.indexOf(phrase) >= 0) rank = 2;
    return {title: document.title, titleFolded: document.titleFolded,
        rank: rank, score: score, snippet: snippet(document, bodyTokens),
        bodyMatch: bodyTokens.length > 0};
}

function compareResults(left, right) {
    if (left.rank !== right.rank) return left.rank - right.rank;
    if (left.score !== right.score) return right.score - left.score;
    if (left.titleFolded !== right.titleFolded) return left.titleFolded < right.titleFolded ? -1 : 1;
    return left.title === right.title ? 0 : (left.title < right.title ? -1 : 1);
}

function search(documents, query) {
    var queryTokens = tokens(query);
    var phrase = queryTokens.join(" ");
    var results = [];
    for (var i = 0; i < documents.length; ++i) {
        var result = scoreDocument(documents[i], queryTokens, phrase);
        if (result) results.push(result);
    }
    results.sort(compareResults);
    return results;
}
