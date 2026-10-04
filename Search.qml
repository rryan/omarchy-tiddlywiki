import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import "SearchModel.js" as SearchModel

Item {
    id: root
    objectName: "tiddlywikiSearch"
    property var shell: null
    property var manifest: null
    property bool opened: false
    property var _documents: []
    property var _results: []
    property bool _indexLoading: false
    property string _indexError: ""
    property int _indexGeneration: 0
    property int _readGeneration: 0
    property var _indexProcess: null
    property var _readProcess: null
    property bool _readerLoading: false
    property string _readerTitle: ""
    property string _readerMetadata: ""
    property string _readerHtml: ""
    property string _readerError: ""
    readonly property bool loading: _indexLoading
    readonly property bool ranking: debounce.running
    readonly property string query: queryField.text
    readonly property int resultCount: _results.length
    readonly property int selectedIndex: results.currentIndex
    readonly property string selectedTitle: selectedIndex >= 0 && selectedIndex < resultCount
        ? _results[selectedIndex].title : ""
    readonly property bool readerVisible: reader.visible
    readonly property bool readerLoading: _readerLoading
    readonly property string readerTitle: _readerTitle
    readonly property string status: _indexLoading ? "Loading titles and content…"
        : _indexError ? _indexError : ranking ? "Searching…"
        : !resultCount ? "No matching tiddlers." : resultCount + " tiddlers"

    function open(payloadJson) {
        close()
        opened = true
        _indexError = ""
        _documents = []
        clearResults()
        queryField.clear()
        _indexLoading = true
        request("index", {})
        Qt.callLater(function() { if (root.opened) queryField.forceActiveFocus() })
    }

    function close() {
        opened = false
        debounce.stop()
        ++_indexGeneration
        ++_readGeneration
        if (_indexProcess) _indexProcess.running = false
        if (_readProcess) _readProcess.running = false
        _indexProcess = null
        _readProcess = null
        _indexLoading = false
        reader.close()
        clearReader()
        clearResults()
    }

    function dismiss() {
        close()
        if (shell) shell.hide("rryan.tiddlywiki")
    }

    function clearResults() {
        results.currentIndex = -1
        _results = []
    }

    function scheduleSearch() {
        clearResults()
        debounce.stop()
        if (opened && !_indexLoading && !_indexError) debounce.restart()
    }

    function updateResults() {
        results.currentIndex = -1
        _results = SearchModel.search(_documents, queryField.text)
        results.currentIndex = _results.length ? 0 : -1
        if (_results.length) results.positionViewAtIndex(0, ListView.Beginning)
    }

    function moveSelection(delta) {
        if (!resultCount || ranking || loading) return
        results.currentIndex = Math.max(0, Math.min(resultCount - 1, results.currentIndex + delta))
        results.positionViewAtIndex(results.currentIndex, ListView.Contain)
    }

    function focusResults() { results.forceActiveFocus() }

    function clearReader() {
        _readerLoading = false
        _readerTitle = ""
        _readerMetadata = ""
        _readerHtml = ""
        _readerError = ""
    }

    function openSelected() {
        if (!selectedTitle || loading || ranking) return
        ++_readGeneration
        if (_readProcess) _readProcess.running = false
        _readProcess = null
        clearReader()
        _readerTitle = selectedTitle
        _readerLoading = true
        reader.open()
        request("read", {title: selectedTitle})
        Qt.callLater(function() { if (reader.visible) readerText.forceActiveFocus() })
    }

    function request(action, payload) {
        var generation = action === "index" ? ++_indexGeneration : ++_readGeneration
        var process = requestComponent.createObject(root, {action: action,
            payload: JSON.stringify(payload), generation: generation})
        if (action === "index") _indexProcess = process
        else _readProcess = process
        process.running = true
    }

    function isCurrent(action, generation) {
        return opened && (action === "index" ? generation === _indexGeneration
            : generation === _readGeneration && reader.visible)
    }

    function receive(action, generation, line) {
        if (!isCurrent(action, generation)) return
        var result
        try { result = JSON.parse(line) } catch (e) {
            fail(action, "Invalid response from the wiki client.")
            return
        }
        if (!result || !result.ok) {
            fail(action, result && result.error ? String(result.error) : "The wiki request failed.")
            return
        }
        if (action === "index") {
            if (!Array.isArray(result.tiddlers)) {
                fail(action, "The wiki client did not return a tiddler index.")
                return
            }
            _documents = SearchModel.prepareIndex(result.tiddlers)
            _indexLoading = false
            _indexError = ""
            debounce.stop()
            updateResults()
        } else {
            if (!result.tiddler || typeof result.html !== "string") {
                fail(action, "The wiki client did not return readable tiddler content.")
                return
            }
            _readerTitle = String(result.tiddler.title || _readerTitle)
            var tags = Array.isArray(result.tiddler.tags) ? result.tiddler.tags.join(" · ") : ""
            _readerMetadata = String(result.tiddler.type || "text/vnd.tiddlywiki")
                + (tags ? "  |  " + tags : "")
            // Only the backend's sanitized, image-free Qt RichText is rendered.
            _readerHtml = result.html
            _readerLoading = false
        }
    }

    function fail(action, message) {
        if (action === "index") {
            _indexLoading = false
            _indexError = message
            clearResults()
        } else {
            _readerLoading = false
            _readerHtml = ""
            _readerError = message
        }
    }

    Component {
        id: requestComponent
        Process {
            id: process
            property string action
            property string payload
            property int generation
            property bool received: false
            command: ["python3", Qt.resolvedUrl("tiddlywiki.py").toString().replace(/^file:\/\//, ""), action]
            stdinEnabled: true
            onStarted: write(payload + "\n")
            stdout: SplitParser {
                onRead: function(line) {
                    process.received = true
                    root.receive(process.action, process.generation, line)
                }
            }
            onExited: function(exitCode, exitStatus) {
                if (root.isCurrent(action, generation)) {
                    if (!received) root.fail(action, "The wiki client stopped without a response.")
                    if (action === "index") root._indexProcess = null
                    else root._readProcess = null
                }
                destroy()
            }
        }
    }

    Timer { id: debounce; interval: 85; onTriggered: root.updateResults() }

    FloatingWindow {
        id: window
        objectName: "tiddlywikiSearchWindow"
        title: "Search tiddlers — TiddlyWiki"
        visible: root.opened
        implicitWidth: 820
        implicitHeight: 680
        minimumSize: Qt.size(480, 380)
        color: Color.menu.background
        onVisibleChanged: if (!visible && root.opened) root.dismiss()

        Item {
            id: surface
            anchors.fill: parent
            Shortcut {
                sequence: "Escape"
                enabled: root.opened && !reader.visible
                onActivated: root.dismiss()
            }
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 24
                spacing: 12
                Label {
                    text: "Search TiddlyWiki"
                    color: Color.menu.text
                    font.pixelSize: 24
                    font.bold: true
                }
                TextField {
                    id: queryField
                    objectName: "tiddlywikiSearchQuery"
                    Layout.fillWidth: true
                    placeholderText: "Title, acronym, or words in content…"
                    selectByMouse: true
                    color: Color.menu.text
                    palette.base: Color.menu.background
                    palette.text: Color.menu.text
                    palette.highlight: Color.menu.selectedBackground
                    palette.highlightedText: Color.menu.selectedText
                    onTextChanged: root.scheduleSearch()
                    Keys.priority: Keys.BeforeItem
                    Keys.onPressed: function(event) {
                        if (event.key === Qt.Key_Tab && !(event.modifiers & Qt.ShiftModifier)) {
                            root.focusResults()
                            event.accepted = true
                        } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                            root.openSelected()
                            event.accepted = true
                        }
                    }
                }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: Color.menu.background
                    border.color: Color.menu.border
                    radius: 6
                    ListView {
                        id: results
                        objectName: "tiddlywikiSearchResults"
                        anchors.fill: parent
                        anchors.margins: 5
                        clip: true
                        model: root._results
                        currentIndex: -1
                        boundsBehavior: Flickable.StopAtBounds
                        keyNavigationEnabled: false
                        ScrollBar.vertical: ScrollBar {}
                        Keys.priority: Keys.BeforeItem
                        Keys.onPressed: function(event) {
                            if (event.key === Qt.Key_Backtab
                                    || (event.key === Qt.Key_Tab && (event.modifiers & Qt.ShiftModifier))) {
                                queryField.forceActiveFocus()
                            } else if (event.key === Qt.Key_Down || (event.key === Qt.Key_J && event.modifiers === Qt.NoModifier)) {
                                root.moveSelection(1)
                            } else if (event.key === Qt.Key_Up || (event.key === Qt.Key_K && event.modifiers === Qt.NoModifier)) {
                                root.moveSelection(-1)
                            } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                                root.openSelected()
                            } else return
                            event.accepted = true
                        }
                        delegate: ItemDelegate {
                            id: row
                            required property int index
                            required property var modelData
                            width: ListView.view.width
                            height: rowContent.implicitHeight + 20
                            highlighted: index === results.currentIndex
                            focusPolicy: Qt.NoFocus
                            onClicked: {
                                results.currentIndex = index
                                root.focusResults()
                                root.openSelected()
                            }
                            background: Rectangle {
                                color: row.highlighted ? Color.menu.selectedBackground : "transparent"
                                border.color: row.highlighted ? Color.menu.selectedBorder : "transparent"
                                radius: 4
                            }
                            contentItem: Column {
                                id: rowContent
                                spacing: 4
                                Label {
                                    width: parent.width
                                    text: row.modelData.title
                                    textFormat: Text.PlainText
                                    color: row.highlighted ? Color.menu.selectedText : Color.menu.text
                                    font.pixelSize: 17
                                    elide: Text.ElideRight
                                }
                                Label {
                                    width: parent.width
                                    visible: !!row.modelData.snippet
                                    text: row.modelData.snippet
                                    textFormat: Text.PlainText
                                    color: Color.menu.text
                                    opacity: 0.7
                                    elide: Text.ElideRight
                                }
                            }
                        }
                        Label {
                            anchors.centerIn: parent
                            width: Math.max(0, parent.width - 32)
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.Wrap
                            textFormat: Text.PlainText
                            visible: !root.resultCount
                            text: root.status
                            color: Color.menu.text
                        }
                    }
                }
                Label {
                    objectName: "tiddlywikiSearchStatus"
                    Layout.fillWidth: true
                    text: root.status
                    textFormat: Text.PlainText
                    color: Color.menu.text
                    wrapMode: Text.Wrap
                }
                Label {
                    Layout.fillWidth: true
                    text: "Tab: results   ·   j/k or ↑/↓: select   ·   Enter: read   ·   Shift+Tab: query   ·   Esc: close"
                    color: Color.menu.text
                    opacity: 0.65
                    wrapMode: Text.Wrap
                }
            }

            Dialog {
                id: reader
                objectName: "tiddlywikiReader"
                parent: surface
                anchors.centerIn: parent
                width: Math.max(0, parent.width - 40)
                height: Math.max(0, parent.height - 40)
                modal: true
                focus: true
                closePolicy: Popup.CloseOnEscape
                padding: 20
                palette.window: Color.menu.background
                palette.base: Color.menu.background
                palette.text: Color.menu.text
                palette.windowText: Color.menu.text
                palette.buttonText: Color.menu.text
                palette.highlight: Color.menu.selectedBackground
                palette.highlightedText: Color.menu.selectedText
                Overlay.modal: Rectangle { color: Color.menu.scrim }
                background: Rectangle {
                    color: Color.menu.background
                    border.color: Color.menu.border
                    radius: 8
                }
                header: Label {
                    objectName: "tiddlywikiReaderTitle"
                    text: root._readerTitle
                    textFormat: Text.PlainText
                    color: Color.menu.text
                    font.pixelSize: 23
                    font.bold: true
                    wrapMode: Text.Wrap
                    padding: 20
                }
                onClosed: {
                    ++root._readGeneration
                    if (root._readProcess) root._readProcess.running = false
                    root._readProcess = null
                    root.clearReader()
                    if (root.opened) Qt.callLater(function() {
                        if (root.opened && !reader.visible) root.focusResults()
                    })
                }
                contentItem: ColumnLayout {
                    spacing: 12
                    Label {
                        objectName: "tiddlywikiReaderMetadata"
                        Layout.fillWidth: true
                        text: root._readerMetadata
                        textFormat: Text.PlainText
                        color: Color.menu.text
                        opacity: 0.75
                        visible: !!text
                        wrapMode: Text.Wrap
                    }
                    Label {
                        objectName: "tiddlywikiReaderStatus"
                        Layout.fillWidth: true
                        visible: root.readerLoading || !!root._readerError
                        text: root.readerLoading ? "Loading tiddler…" : root._readerError
                        textFormat: Text.PlainText
                        color: Color.menu.text
                        wrapMode: Text.Wrap
                    }
                    ScrollView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        TextArea {
                            id: readerText
                            objectName: "tiddlywikiReaderText"
                            text: root._readerHtml
                            textFormat: TextEdit.RichText
                            readOnly: true
                            selectByMouse: true
                            persistentSelection: true
                            wrapMode: TextEdit.Wrap
                            color: Color.menu.text
                            background: null
                            // TextArea does not launch URLs; sanitized HTML contains no links or images.
                        }
                    }
                    Button {
                        objectName: "tiddlywikiReaderClose"
                        Layout.alignment: Qt.AlignRight
                        text: "Close reader"
                        background: Rectangle {
                            implicitWidth: 120
                            implicitHeight: 34
                            color: Color.menu.selectedBackground
                            border.color: Color.menu.border
                            radius: 4
                        }
                        onClicked: reader.close()
                    }
                }
            }
        }
    }
}
