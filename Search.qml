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
    property bool _indexReady: false
    property bool _indexLoading: false
    property bool _indexRefreshing: false
    property bool _searchPending: false
    property string _rankedQuery: ""
    property string _indexError: ""
    property int _indexGeneration: 0
    property int _readGeneration: 0
    property var _indexProcess: null
    property var _readProcess: null
    property bool _readerLoading: false
    property string _readerTitle: ""
    property string _readerMetadata: ""
    property var _readerTags: []
    property string _readerHtml: ""
    property string _readerError: ""
    readonly property bool loading: _indexLoading
    readonly property bool refreshing: _indexRefreshing
    readonly property bool ranking: _searchPending
    readonly property string query: queryField.text
    readonly property int resultCount: _results.length
    readonly property int selectedIndex: results.currentIndex
    readonly property string selectedTitle: selectedIndex >= 0 && selectedIndex < resultCount
        ? _results[selectedIndex].title : ""
    readonly property bool readerVisible: reader.visible
    readonly property bool readerLoading: _readerLoading
    readonly property string readerTitle: _readerTitle
    readonly property string status: _indexLoading ? "Loading titles and content…"
        : ranking ? "Searching…"
        : _indexError ? (_indexReady ? "Refresh failed: " : "") + _indexError
        : _indexRefreshing ? "Refreshing…  ·  " + resultCount + " tiddlers"
        : !resultCount ? "No matching tiddlers." : resultCount + " tiddlers"

    function open(payloadJson) {
        close()
        _indexError = ""
        queryField.clear()
        opened = true
        _indexLoading = !_indexReady
        _indexRefreshing = _indexReady
        if (_indexReady) {
            updateResults()
            results.currentIndex = _results.length ? 0 : -1
            if (_results.length) results.positionViewAtIndex(0, ListView.Beginning)
        } else clearResults()
        request("index", {})
        Qt.callLater(function() { if (root.opened) queryField.forceActiveFocus() })
    }

    function close() {
        opened = false
        debounce.stop()
        _searchPending = false
        ++_indexGeneration
        ++_readGeneration
        if (_indexProcess) _indexProcess.running = false
        if (_readProcess) _readProcess.running = false
        _indexProcess = null
        _readProcess = null
        _indexLoading = false
        _indexRefreshing = false
        reader.close()
        clearReader()
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
        debounce.stop()
        _searchPending = opened && _indexReady
        if (_searchPending) debounce.restart()
    }

    function updateResults() {
        var next = SearchModel.search(_documents, queryField.text)
        var unchanged = next.length === _results.length
        for (var i = 0; unchanged && i < next.length; ++i) {
            unchanged = next[i].title === _results[i].title
                && next[i].snippet === _results[i].snippet
        }
        if (!unchanged) {
            var previousTitle = _rankedQuery === queryField.text ? selectedTitle : ""
            var nextIndex = next.length ? 0 : -1
            for (var j = 0; previousTitle && j < next.length; ++j) {
                if (next[j].title === previousTitle) {
                    nextIndex = j
                    break
                }
            }
            results.currentIndex = -1
            _results = next
            results.currentIndex = nextIndex
            if (nextIndex >= 0) results.positionViewAtIndex(nextIndex,
                previousTitle ? ListView.Contain : ListView.Beginning)
        } else if (_rankedQuery !== queryField.text && next.length) {
            results.currentIndex = 0
            results.positionViewAtIndex(0, ListView.Beginning)
        }
        _rankedQuery = queryField.text
        _searchPending = false
    }

    function moveSelection(delta) {
        if (!resultCount || ranking || loading || reader.visible) return
        results.currentIndex = Math.max(0, Math.min(resultCount - 1, results.currentIndex + delta))
        results.positionViewAtIndex(results.currentIndex, ListView.Contain)
    }

    function focusResults() { if (!reader.visible) results.forceActiveFocus() }

    function clearReader() {
        _readerLoading = false
        _readerTitle = ""
        _readerMetadata = ""
        _readerTags = []
        _readerHtml = ""
        _readerError = ""
    }

    function openSelected() {
        if (!selectedTitle || loading || ranking || _rankedQuery !== queryField.text
                || reader.visible) return
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

    function localTimestamp(value) {
        if (typeof value !== "string" || !/^\d{17}$/.test(value)) return ""
        var year = Number(value.slice(0, 4))
        var month = Number(value.slice(4, 6)) - 1
        var day = Number(value.slice(6, 8))
        var hour = Number(value.slice(8, 10))
        var minute = Number(value.slice(10, 12))
        var second = Number(value.slice(12, 14))
        var date = new Date(0)
        date.setUTCFullYear(year, month, day)
        date.setUTCHours(hour, minute, second, Number(value.slice(14, 17)))
        if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month
                || date.getUTCDate() !== day || date.getUTCHours() !== hour
                || date.getUTCMinutes() !== minute || date.getUTCSeconds() !== second)
            return ""
        return Qt.formatDateTime(date, "d MMM yyyy, HH:mm")
    }

    function readerMetadata(tiddler) {
        var modifier = typeof tiddler.modifier === "string" ? tiddler.modifier.trim() : ""
        var creator = typeof tiddler.creator === "string" ? tiddler.creator.trim() : ""
        var author = modifier || creator
        var date = localTimestamp(tiddler.modified) || localTimestamp(tiddler.created)
        return author && date ? author + "  ·  " + date : author || date
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
            _indexReady = true
            _indexLoading = false
            _indexRefreshing = false
            _indexError = ""
            debounce.stop()
            updateResults()
        } else {
            if (!result.tiddler || typeof result.html !== "string") {
                fail(action, "The wiki client did not return readable tiddler content.")
                return
            }
            _readerTitle = String(result.tiddler.title || _readerTitle)
            _readerMetadata = readerMetadata(result.tiddler)
            _readerTags = Array.isArray(result.tiddler.tags)
                ? result.tiddler.tags.filter(function(tag) {
                    return typeof tag === "string" && tag.length > 0
                }) : []
            // Only the backend's sanitized, image-free Qt RichText is rendered.
            _readerHtml = result.html
            _readerLoading = false
            readerScroller.contentY = readerScroller.originY
        }
    }

    function fail(action, message) {
        if (action === "index") {
            _indexLoading = false
            _indexRefreshing = false
            _indexError = message
            if (!_indexReady) clearResults()
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

    Timer { id: debounce; interval: 25; onTriggered: root.updateResults() }

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
                    enabled: !reader.visible
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
                        enabled: !reader.visible
                        flickableDirection: Flickable.VerticalFlick
                        pixelAligned: false
                        model: root._results
                        currentIndex: -1
                        boundsBehavior: Flickable.StopAtBounds
                        keyNavigationEnabled: false
                        ScrollBar.vertical: ScrollBar {}
                        WheelScroll {
                            objectName: "tiddlywikiResultsWheel"
                            scroller: results
                        }
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
                                if (root.loading || root.ranking || reader.visible) return
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
                        objectName: "tiddlywikiReaderStatus"
                        Layout.fillWidth: true
                        visible: root.readerLoading || !!root._readerError
                        text: root.readerLoading ? "Loading tiddler…" : root._readerError
                        textFormat: Text.PlainText
                        color: Color.menu.text
                        wrapMode: Text.Wrap
                    }
                    Flickable {
                        id: readerScroller
                        objectName: "tiddlywikiReaderFlickable"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        flickableDirection: Flickable.VerticalFlick
                        boundsBehavior: Flickable.StopAtBounds
                        pixelAligned: false
                        // Mouse drags select text; touchscreen drags still flick normally.
                        acceptedButtons: Qt.NoButton
                        contentWidth: width
                        contentHeight: readerContent.height
                        ScrollBar.vertical: ScrollBar {}
                        WheelScroll {
                            id: readerWheel
                            objectName: "tiddlywikiReaderWheel"
                            scroller: readerScroller
                        }
                        function ensureCursorVisible() {
                            var top = readerText.y + readerText.cursorRectangle.y
                            var bottom = top + readerText.cursorRectangle.height
                            var destination = contentY
                            if (top < contentY) destination = top
                            else if (bottom > contentY + height) destination = bottom - height
                            if (destination !== contentY) {
                                contentY = readerWheel.bounded(destination)
                            }
                        }
                        Column {
                            id: readerContent
                            width: Math.max(0, readerScroller.width - 14)
                            spacing: 16
                            Label {
                                objectName: "tiddlywikiReaderMetadata"
                                width: parent.width
                                text: root._readerMetadata
                                textFormat: Text.PlainText
                                color: Color.menu.text
                                opacity: 0.7
                                visible: !!text
                                wrapMode: Text.Wrap
                            }
                            Flow {
                                id: readerTags
                                objectName: "tiddlywikiReaderTags"
                                width: parent.width
                                spacing: 8
                                visible: root._readerTags.length > 0
                                Repeater {
                                    model: root._readerTags
                                    delegate: Rectangle {
                                        objectName: "tiddlywikiReaderTag"
                                        required property string modelData
                                        width: Math.min(readerTags.width, tagText.implicitWidth + 20)
                                        height: tagText.implicitHeight + 12
                                        radius: 6
                                        color: Color.menu.selectedBackground
                                        border.color: Color.menu.border
                                        Label {
                                            id: tagText
                                            x: 10
                                            y: 6
                                            width: Math.max(0, parent.width - 20)
                                            text: parent.modelData
                                            textFormat: Text.PlainText
                                            wrapMode: Text.WrapAnywhere
                                            color: Color.menu.text
                                            font.pixelSize: 14
                                        }
                                    }
                                }
                            }
                            Rectangle {
                                objectName: "tiddlywikiReaderDivider"
                                width: parent.width
                                height: 1
                                visible: !!root._readerMetadata || root._readerTags.length > 0
                                color: Color.menu.border
                            }
                            TextEdit {
                                id: readerText
                                objectName: "tiddlywikiReaderText"
                                width: parent.width
                                height: contentHeight
                                text: root._readerHtml
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
                                onCursorPositionChanged: if (activeFocus) readerScroller.ensureCursorVisible()
                                // The backend supplies body-only, image-free HTML without links.
                            }
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
