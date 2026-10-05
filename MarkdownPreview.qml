import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell.Io
import qs.Commons

Item {
    id: root
    objectName: "tiddlywikiMarkdownPreview"
    property bool active: false
    property string draftTitle: ""
    property string draftText: ""
    property string draftTags: ""
    property string draftType: "text/x-markdown"
    property var context: []
    property int _generation: 0
    property var _process: null
    property string _html: ""
    property string _error: ""
    property bool _loading: false
    readonly property bool markdown: {
        var mime = draftType.split(";", 1)[0].trim().toLowerCase()
        return mime === "text/x-markdown" || mime === "text/markdown"
    }
    readonly property bool previewVisible: active && markdown
    visible: previewVisible

    function schedule() {
        debounce.stop()
        ++_generation
        if (_process) _process.running = false
        _process = null
        if (!previewVisible) _html = ""
        _error = ""
        _loading = previewVisible
        if (previewVisible) debounce.restart()
    }
    function render() {
        if (!previewVisible) return
        var process = previewProcess.createObject(root, {
            generation: _generation,
            payload: JSON.stringify({title: draftTitle, text: draftText, tags: draftTags,
                type: draftType, context: context})
        })
        _process = process
        process.running = true
    }
    function isCurrent(generation) {
        return previewVisible && generation === _generation
    }
    function fail(message) {
        _loading = false
        _html = ""
        _error = message
    }
    function receive(generation, line) {
        if (!isCurrent(generation)) return
        var result
        try { result = JSON.parse(line) } catch (e) {
            fail("The local preview returned an invalid response.")
            return
        }
        if (!result || result.ok !== true || typeof result.html !== "string") {
            fail(result && typeof result.error === "string" ? result.error
                : "The local Markdown preview could not be rendered. Your draft is unchanged.")
            return
        }
        _html = result.html
        _error = ""
        _loading = false
    }

    onPreviewVisibleChanged: schedule()
    onDraftTitleChanged: schedule()
    onDraftTextChanged: schedule()
    onDraftTagsChanged: schedule()
    onDraftTypeChanged: schedule()
    onContextChanged: schedule()
    Component.onCompleted: schedule()
    Component.onDestruction: if (_process) _process.running = false
    Timer { id: debounce; interval: 200; onTriggered: root.render() }
    Component {
        id: previewProcess
        Process {
            id: process
            property int generation
            property string payload
            property bool received: false
            command: ["python3", Qt.resolvedUrl("tiddlywiki.py").toString().replace(/^file:\/\//, ""), "preview"]
            stdinEnabled: true
            onStarted: {
                write(payload + "\n")
                payload = ""
            }
            stdout: SplitParser {
                onRead: function(line) {
                    if (process.received) return
                    process.received = true
                    root.receive(process.generation, line)
                }
            }
            onExited: function(exitCode, exitStatus) {
                if (root.isCurrent(generation)) {
                    if (!received) root.fail("The local preview stopped without a response. Your draft is unchanged.")
                    root._process = null
                }
                destroy()
            }
        }
    }

    ColumnLayout {
            anchors.fill: parent
            anchors.margins: 0
            spacing: 12
            Label {
                Layout.fillWidth: true
                text: root.draftTitle || "Untitled draft"
                textFormat: Text.PlainText
                color: Color.menu.text
                font.pixelSize: 24
                font.bold: true
                wrapMode: Text.Wrap
            }
            Label {
                objectName: "tiddlywikiPreviewStatus"
                Layout.fillWidth: true
                visible: root._loading || !!root._error
                text: root._loading ? "Rendering Markdown…" : root._error
                textFormat: Text.PlainText
                color: root._error ? "#ef8080" : Color.menu.text
                wrapMode: Text.Wrap
            }
            Flickable {
                id: scroller
                objectName: "tiddlywikiPreviewFlickable"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                flickableDirection: Flickable.VerticalFlick
                boundsBehavior: Flickable.StopAtBounds
                pixelAligned: false
                acceptedButtons: Qt.NoButton
                contentWidth: width
                contentHeight: previewText.height
                ScrollBar.vertical: ScrollBar {}
                WheelScroll { id: wheel; objectName: "tiddlywikiPreviewWheel"; scroller: scroller }
                function scrollViewport(direction, page) {
                    cancelFlick()
                    var line = Math.max(1, metrics.lineSpacing)
                    var distance = page ? Math.max(line, height - line) : line
                    contentY = wheel.bounded(contentY + direction * distance)
                }
                function ensureCursorVisible() {
                    var top = previewText.cursorRectangle.y
                    var bottom = top + previewText.cursorRectangle.height
                    if (top < contentY) contentY = wheel.bounded(top)
                    else if (bottom > contentY + height) contentY = wheel.bounded(bottom - height)
                }
                TextEdit {
                    id: previewText
                    objectName: "tiddlywikiPreviewText"
                    width: Math.max(0, scroller.width - 14)
                    height: contentHeight
                    text: root._html
                    // The local renderer returns sanitized, image-free, link-free body HTML.
                    textFormat: TextEdit.RichText
                    readOnly: true
                    selectByMouse: true
                    persistentSelection: true
                    activeFocusOnTab: true
                    wrapMode: TextEdit.Wrap
                    color: Color.menu.text
                    selectionColor: Color.menu.selectedBackground
                    selectedTextColor: Color.menu.selectedText
                    font.pixelSize: 16
                    onCursorPositionChanged: if (activeFocus) scroller.ensureCursorVisible()
                    Keys.onPressed: function(event) {
                        if (!activeFocus) return
                        if (event.key === Qt.Key_PageDown || event.key === Qt.Key_PageUp) {
                            scroller.scrollViewport(event.key === Qt.Key_PageDown ? 1 : -1, true)
                            event.accepted = true
                        }
                    }
                }
            }
            FontMetrics { id: metrics; font: previewText.font }
        }
}
