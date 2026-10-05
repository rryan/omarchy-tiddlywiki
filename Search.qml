import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell.Io
import qs.Commons
import "SearchModel.js" as SearchModel

Item {
    id: root
    objectName: "tiddlywikiSearch"
    signal dismissRequested()
    signal editRequested(var fields)
    property bool _viewing: false
    property var _readerTiddler: null
    property bool _readerEditable: false
    property string _waitingReadTitle: ""
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
    readonly property var context: _documents.map(function(document) { return document.fields })
    readonly property string selectedTitle: selectedIndex >= 0 && selectedIndex < resultCount
        ? _results[selectedIndex].title : ""
    readonly property bool readerVisible: _viewing
    readonly property bool readerEditable: _readerEditable && !_readerLoading && !!_readerTiddler
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
        Qt.callLater(function() { if (root.opened && root.visible && !root.readerVisible) queryField.forceActiveFocus() })
    }

    function ensureIndex() {
        opened = true
        if (!_indexReady && !_indexLoading) refreshIndex()
    }

    function refreshIndex() {
        opened = true
        _indexError = ""
        _indexLoading = !_indexReady
        _indexRefreshing = _indexReady
        request("index", {})
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
        _viewing = false
        _waitingReadTitle = ""
        clearReader()
    }

    function dismiss() { dismissRequested() }

    function back() {
        ++_readGeneration
        if (_readProcess) _readProcess.running = false
        _readProcess = null
        _waitingReadTitle = ""
        _viewing = false
        clearReader()
        Qt.callLater(function() { if (root.opened && root.visible && !root.readerVisible) root.focusResults() })
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
        if (!resultCount || ranking || loading || readerVisible) return
        results.currentIndex = Math.max(0, Math.min(resultCount - 1, results.currentIndex + delta))
        results.positionViewAtIndex(results.currentIndex, ListView.Contain)
    }

    function focusResults() { if (opened && visible && !readerVisible) results.forceActiveFocus() }

    function focusReader() { if (opened && visible && readerVisible) readerText.forceActiveFocus() }

    function editCurrent() {
        if (opened && visible && readerVisible && readerEditable) editRequested(_readerTiddler)
    }

    function clearReader() {
        _readerLoading = false
        _readerTitle = ""
        _readerMetadata = ""
        _readerTags = []
        _readerHtml = ""
        _readerError = ""
        _readerTiddler = null
        _readerEditable = false
    }

    function openSelected() {
        if (!selectedTitle || loading || ranking || _rankedQuery !== queryField.text || readerVisible) return
        openTiddler(selectedTitle)
    }

    function openTiddler(title) {
        if (typeof title !== "string" || !title) return
        ensureIndex()
        ++_readGeneration
        if (_readProcess) _readProcess.running = false
        _readProcess = null
        clearReader()
        _readerTitle = title
        _readerLoading = true
        _viewing = true
        if (_indexReady) {
            _waitingReadTitle = ""
            request("read", {title: title, context: context})
        } else {
            _waitingReadTitle = title
            if (!_indexLoading) fail("read", _indexError || "Could not load the wiki index.")
        }
        Qt.callLater(function() { root.focusReader() })
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
        var previous = action === "index" ? _indexProcess : _readProcess
        if (previous) previous.running = false
        var process = requestComponent.createObject(root, {action: action,
            payload: JSON.stringify(payload), generation: generation})
        if (action === "index") _indexProcess = process
        else _readProcess = process
        process.running = true
    }

    function isCurrent(action, generation) {
        return opened && (action === "index" ? generation === _indexGeneration
            : generation === _readGeneration && readerVisible)
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
            if (_waitingReadTitle && readerVisible) {
                var title = _waitingReadTitle
                _waitingReadTitle = ""
                request("read", {title: title, context: context})
            }
        } else {
            if (!result.tiddler || typeof result.html !== "string") {
                fail(action, "The wiki client did not return readable tiddler content.")
                return
            }
            _readerTitle = String(result.tiddler.title || _readerTitle)
            _readerTiddler = result.tiddler
            _readerEditable = result.editable === true
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
            if (_waitingReadTitle && readerVisible) {
                _waitingReadTitle = ""
                fail("read", "Could not load the wiki index: " + message)
            }
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

    Shortcut {
        sequence: "Escape"
        enabled: root.opened && root.visible && root.enabled
        onActivated: root.readerVisible ? root.back() : root.dismiss()
    }
    Shortcut {
        sequence: "E"
        enabled: root.opened && root.visible && root.enabled && root.readerVisible && root.readerEditable
        onActivated: root.editCurrent()
    }

    StackLayout {
        anchors.fill: parent
        anchors.margins: 24
        currentIndex: root.readerVisible ? 1 : 0
        ColumnLayout {
            objectName: "tiddlywikiSearchPane"
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
                    } else if (event.modifiers === Qt.NoModifier
                            && (event.key === Qt.Key_Down || event.key === Qt.Key_Up)) {
                        root.moveSelection(event.key === Qt.Key_Down ? 1 : -1)
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
                    flickableDirection: Flickable.VerticalFlick
                    pixelAligned: false
                    model: root._results
                    currentIndex: -1
                    boundsBehavior: Flickable.StopAtBounds
                    keyNavigationEnabled: false
                    ScrollBar.vertical: ScrollBar {}
                    WheelScroll { objectName: "tiddlywikiResultsWheel"; scroller: results }
                    Keys.priority: Keys.BeforeItem
                    Keys.onPressed: function(event) {
                        if (event.key === Qt.Key_Backtab
                                || (event.key === Qt.Key_Tab && (event.modifiers & Qt.ShiftModifier))) {
                            queryField.forceActiveFocus()
                        } else if (event.key === Qt.Key_Slash && event.modifiers === Qt.NoModifier) {
                            queryField.forceActiveFocus()
                        } else if (event.modifiers === Qt.NoModifier
                                && (event.key === Qt.Key_Down || event.key === Qt.Key_J)) {
                            root.moveSelection(1)
                        } else if (event.modifiers === Qt.NoModifier
                                && (event.key === Qt.Key_Up || event.key === Qt.Key_K)) {
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
                            if (root.loading || root.ranking || root.readerVisible) return
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
                text: "↑/↓: select   ·   Tab: results (j/k)   ·   Enter: read   ·   Shift+Tab: query   ·   Esc: close"
                color: Color.menu.text
                opacity: 0.65
                wrapMode: Text.Wrap
            }
        }
        ColumnLayout {
            objectName: "tiddlywikiViewPane"
            spacing: 12
            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                Button {
                    objectName: "tiddlywikiViewBack"
                    text: "←"
                    font.pixelSize: 23
                    palette.buttonText: Color.menu.text
                    Accessible.name: "Back to search results"
                    ToolTip.visible: hovered
                    ToolTip.text: "Back to search (Escape)"
                    background: Rectangle {
                        implicitWidth: 40
                        implicitHeight: 36
                        radius: 4
                        color: Color.menu.selectedBackground
                        border.color: Color.menu.border
                    }
                    onClicked: root.back()
                }
                Label {
                    objectName: "tiddlywikiReaderTitle"
                    Layout.fillWidth: true
                    text: root._readerTitle
                    textFormat: Text.PlainText
                    color: Color.menu.text
                    font.pixelSize: 23
                    font.bold: true
                    wrapMode: Text.Wrap
                }
                Button {
                    objectName: "tiddlywikiViewEdit"
                    text: "Edit"
                    enabled: root.readerEditable
                    palette.buttonText: Color.menu.text
                    ToolTip.visible: hovered
                    ToolTip.text: "Edit this tiddler (e)"
                    background: Rectangle {
                        implicitWidth: 64
                        implicitHeight: 36
                        radius: 4
                        color: Color.menu.selectedBackground
                        border.color: Color.menu.border
                    }
                    onClicked: root.editCurrent()
                }
            }
            FontMetrics { id: readerFontMetrics; font: readerText.font }
            Shortcut {
                sequence: "Down"
                enabled: root.opened && root.visible && root.enabled && root.readerVisible
                onActivated: readerScroller.scrollViewport(1, false)
            }
            Shortcut {
                sequence: "Up"
                enabled: root.opened && root.visible && root.enabled && root.readerVisible
                onActivated: readerScroller.scrollViewport(-1, false)
            }
            Shortcut {
                sequence: "PgDown"
                enabled: root.opened && root.visible && root.enabled && root.readerVisible
                onActivated: readerScroller.scrollViewport(1, true)
            }
            Shortcut {
                sequence: "PgUp"
                enabled: root.opened && root.visible && root.enabled && root.readerVisible
                onActivated: readerScroller.scrollViewport(-1, true)
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
                WheelScroll { id: readerWheel; objectName: "tiddlywikiReaderWheel"; scroller: readerScroller }
                function ensureCursorVisible() {
                    var top = readerText.y + readerText.cursorRectangle.y
                    var bottom = top + readerText.cursorRectangle.height
                    var destination = contentY
                    if (top < contentY) destination = top
                    else if (bottom > contentY + height) destination = bottom - height
                    if (destination !== contentY) contentY = readerWheel.bounded(destination)
                }
                function scrollViewport(direction, page) {
                    cancelFlick()
                    var line = Math.max(1, readerFontMetrics.lineSpacing)
                    var distance = page ? Math.max(line, height - line) : line
                    contentY = readerWheel.bounded(contentY + direction * distance)
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
                    }
                }
            }
            Label {
                Layout.fillWidth: true
                text: "↑/↓: scroll   ·   PgUp/PgDn: page"
                    + (root.readerEditable ? "   ·   e: edit" : "") + "   ·   Esc: back"
                color: Color.menu.text
                opacity: 0.65
                wrapMode: Text.Wrap
            }
        }
    }
}
