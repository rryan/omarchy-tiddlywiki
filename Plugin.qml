import QtQuick
import QtQuick.Window
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons

Item {
    id: root
    objectName: "tiddlywikiPlugin"
    property var shell: null
    property var manifest: null
    property bool opened: false
    property string _mode: "create"
    readonly property string mode: _mode
    property int _prepareGeneration: 0
    property var _prepareProcess: null
    property string _prepareError: ""
    property bool _editorFromView: false

    function open(payloadJson) {
        var payload = {}
        try { payload = JSON.parse(payloadJson || "{}") || {} } catch (e) {}
        opened = true
        if (!editor.saving) {
            _editorFromView = false
            cancelPreparation()
            editor.close()
            if (payload.mode === "search") {
                _mode = "search"
                search.open(payloadJson)
            } else if (payload.mode === "today" || payload.mode === "quick-note") {
                prepare(payload.mode)
            } else {
                search.back()
                search.ensureIndex()
                _mode = "create"
                editor.open(payloadJson)
            }
        }
        Qt.callLater(function() {
            if (root.opened && surface.Window.window) surface.Window.window.requestActivate()
        })
    }

    function close() {
        cancelPreparation()
        opened = false
        search.close()
        editor.close()
    }

    function dismiss() {
        close()
        if (shell) shell.hide("rryan.tiddlywiki")
    }

    function editTiddler(fields) {
        _editorFromView = true
        if (editor.openForEdit(fields)) _mode = "edit"
    }

    function showSaved(title) {
        if (!opened) return
        if (editor.closeAfterSave) {
            dismiss()
            return
        }
        var showView = _mode === "create" || _mode === "edit"
            || (_mode === "view" && search.readerTitle === title)
        search.refreshIndex()
        if (showView) {
            _mode = "view"
            search.openTiddler(title)
        }
    }
    function cancelPreparation() {
        ++_prepareGeneration
        if (_prepareProcess) _prepareProcess.running = false
        _prepareProcess = null
    }

    function prepare(kind) {
        search.back()
        _mode = "prepare"
        _prepareError = ""
        _prepareProcess = prepareComponent.createObject(root, {
            payload: JSON.stringify({kind: kind}), generation: _prepareGeneration})
        _prepareProcess.running = true
    }

    function prepared(generation, line) {
        if (!opened || generation !== _prepareGeneration || _mode !== "prepare") return
        var result
        try { result = JSON.parse(line) } catch (e) {
            _prepareError = "Invalid response while opening the tiddler."
            return
        }
        if (!result || !result.ok) {
            _prepareError = result && result.error ? String(result.error) : "Could not open the tiddler."
            return
        }
        editor.openPrepared(result)
    }


    Component {
        id: prepareComponent
        Process {
            id: process
            property string payload
            property int generation
            property bool received: false
            command: ["python3", Qt.resolvedUrl("tiddlywiki.py").toString().replace(/^file:\/\//, ""), "prepare"]
            stdinEnabled: true
            onStarted: write(payload + "\n")
            stdout: SplitParser {
                onRead: function(line) {
                    process.received = true
                    root.prepared(process.generation, line)
                }
            }
            onExited: function(exitCode, exitStatus) {
                if (root.opened && generation === root._prepareGeneration) {
                    if (!received) root._prepareError = "The wiki client stopped without a response."
                    root._prepareProcess = null
                }
                destroy()
            }
        }
    }

    FloatingWindow {
        id: window
        objectName: "tiddlywikiWindow"
        title: "TiddlyWiki"
        visible: root.opened
        implicitWidth: 1200
        implicitHeight: 760
        minimumSize: Qt.size(760, 640)
        color: Color.menu.background
        onVisibleChanged: if (!visible && root.opened) root.dismiss()

        Item {
            id: surface
            anchors.fill: parent
            Search {
                id: search
                anchors.fill: parent
                visible: root._mode === "search" || root._mode === "view"
                enabled: !editor.confirmationPending
                onDismissRequested: root.dismiss()
                onReaderVisibleChanged: {
                    if (root.opened && root._mode !== "create" && root._mode !== "edit")
                        root._mode = readerVisible ? "view" : "search"
                }
                onEditRequested: function(fields) { root.editTiddler(fields) }
            }
            Editor {
                id: editor
                anchors.fill: parent
                visible: root._mode === "create" || root._mode === "edit"
                context: search.context
                onSavedTiddler: function(title) { root.showSaved(title) }
                onPreparedOpened: function(mode, title) {
                    root._editorFromView = false
                    root._mode = mode
                    Qt.callLater(function() {
                        if (root.opened && editor.visible) search.ensureIndex()
                    })
                }
                onPreparedCancelled: root.dismiss()
                onEditOpened: root._mode = "edit"
                onCloseRequested: {
                    var title = editor.currentDraft().title
                    editor.close()
                    if (root._editorFromView) {
                        root._mode = "view"
                        search.openTiddler(title)
                    } else root.dismiss()
                }
            }
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 24
                visible: root._mode === "prepare"
                Label {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    text: root._prepareError || "Opening tiddler…"
                    textFormat: Text.PlainText
                    color: root._prepareError ? "#ef8080" : Color.menu.text
                    wrapMode: Text.Wrap
                    verticalAlignment: Text.AlignVCenter
                    horizontalAlignment: Text.AlignHCenter
                }
                Button { text: "Back"; onClicked: root.dismiss() }
                Shortcut {
                    sequence: "Escape"
                    enabled: root.opened && root._mode === "prepare" && !editor.confirmationPending
                    onActivated: root.dismiss()
                }
            }
        }
    }
}
