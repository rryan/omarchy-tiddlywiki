import QtQuick

// Input is backend-sanitized body HTML. Keep native text selection and layout;
// Qt RichText loads data URLs, but does not implement CSS max-width for images.
TextEdit {
    id: root
    property string html: ""
    readonly property bool updatingLayout: _updatingLayout
    property bool _updatingLayout: false
    property bool _ready: false
    property var _parts: []
    property var _images: []
    property int _nextImage: 0
    property var _probing: null

    textFormat: TextEdit.RichText
    readOnly: true
    selectByMouse: true
    persistentSelection: true
    activeFocusOnTab: true
    wrapMode: TextEdit.Wrap

    function attribute(tag, name) {
        var match = new RegExp("\\b" + name + "\\s*=\\s*(?:\"([^\"]*)\"|'([^']*)'|([^\\s\"'=<>`]+))", "i").exec(tag)
        return match ? (match[1] !== undefined ? match[1]
            : match[2] !== undefined ? match[2] : match[3]) : ""
    }
    function positive(value) {
        return /^(?:\d+(?:\.\d*)?|\.\d+)$/.test(value) && Number(value) > 0
            && isFinite(Number(value)) ? Number(value) : 0
    }
    function parse() {
        probe.source = ""
        _probing = null
        _nextImage = 0
        var parts = []
        var images = []
        var sources = Object.create(null)
        // Retain only dimensions for images still present in this document.
        // Typing around an unchanged Markdown image should not decode it again.
        var previous = Object.create(null)
        _images.forEach(function(image) { if (image.done) previous[image.source] = image })
        var pattern = /<img\b[^>]*>/gi
        var offset = 0
        var match
        while ((match = pattern.exec(html)) !== null) {
            parts.push(html.slice(offset, match.index))
            var tag = match[0]
            var source = attribute(tag, "src")
            var alt = attribute(tag, "alt").replace(/"/g, "&quot;")
            // Defense in depth: only the backend's embedded image bytes reach Qt.
            if (/^data:image\/[a-z0-9.+-]+;base64,[a-z0-9+/=]+$/i.test(source)) {
                var image = sources[source]
                if (!image) {
                    image = previous[source] || { source: source, width: 0, height: 0, done: false }
                    sources[source] = image
                    images.push(image)
                }
                parts.push({ image: image, alt: alt,
                    width: positive(attribute(tag, "width")),
                    height: positive(attribute(tag, "height")) })
            } else {
                parts.push("[Image unavailable" + (alt ? ": " + alt : "") + "]")
            }
            offset = pattern.lastIndex
        }
        parts.push(html.slice(offset))
        _parts = parts
        _images = images
        refresh(false)
        Qt.callLater(loadNext)
    }
    function loadNext() {
        if (_probing) return
        while (_nextImage < _images.length && _images[_nextImage].done) ++_nextImage
        if (_nextImage >= _images.length) return
        _probing = _images[_nextImage++]
        probe.source = _probing.source
    }
    function decoded(success) {
        if (!_probing) return
        _probing.width = success ? probe.implicitWidth : 0
        _probing.height = success ? probe.implicitHeight : 0
        _probing.done = true
        _probing = null
        // The probe is never rendered. Release its uncached decoded pixels before
        // TextEdit loads the inline resource, and before decoding the next image.
        probe.source = ""
        refresh(true)
        Qt.callLater(loadNext)
    }
    function refresh(preserveCursor) {
        var available = Math.max(1, Math.floor(width - leftPadding - rightPadding - 2))
        var output = _parts.map(function(part) {
            if (typeof part === "string") return part
            var image = part.image
            if (!image.width || !image.height) {
                return "[Image " + (image.done ? "unavailable" : "loading…")
                    + (part.alt ? ": " + part.alt : "") + "]"
            }
            var scale = Math.min(1, available / image.width,
                part.width ? part.width / image.width : 1,
                part.height ? part.height / image.height : 1)
            return '<img src="' + image.source + '" alt="' + part.alt
                + '" width="' + Math.max(1, Math.floor(image.width * scale))
                + '" height="' + Math.max(1, Math.round(image.height * scale)) + '">'
        }).join("")
        if (text === output) return
        var cursor = cursorPosition
        var anchor = cursor === selectionStart ? selectionEnd : selectionStart
        _updatingLayout = true
        text = output
        if (preserveCursor) select(Math.min(anchor, length), Math.min(cursor, length))
        _updatingLayout = false
    }

    onHtmlChanged: if (_ready) parse()
    onWidthChanged: if (_ready) refresh(true)
    onLeftPaddingChanged: if (_ready) refresh(true)
    onRightPaddingChanged: if (_ready) refresh(true)
    Component.onCompleted: {
        _ready = true
        parse()
    }

    Image {
        id: probe
        visible: false
        width: 0
        height: 0
        asynchronous: true
        cache: false
        onStatusChanged: {
            if (status === Image.Ready) root.decoded(true)
            else if (status === Image.Error) root.decoded(false)
        }
    }
}
