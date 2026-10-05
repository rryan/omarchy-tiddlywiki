import QtQuick
import QtQuick.Window
import Quickshell
import qs.Commons

Item {
    id: root
    objectName: "tiddlywikiPlugin"
    property var shell: null
    property var manifest: null
    property bool opened: false
    property string _mode: "create"
    readonly property string mode: _mode

    function open(payloadJson) {
        var payload = {}
        try { payload = JSON.parse(payloadJson || "{}") || {} } catch (e) {}
        opened = true
        if (!editor.saving) {
            editor.close()
            if (payload.mode === "search") {
                _mode = "search"
                search.open(payloadJson)
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
        opened = false
        search.close()
        editor.close()
    }

    function dismiss() {
        close()
        if (shell) shell.hide("rryan.tiddlywiki")
    }

    function editTiddler(fields) {
        if (editor.openForEdit(fields)) _mode = "edit"
    }

    function showSaved(title) {
        if (!opened) return
        var showView = _mode === "create" || _mode === "edit"
            || (_mode === "view" && search.readerTitle === title)
        search.refreshIndex()
        if (showView) {
            _mode = "view"
            search.openTiddler(title)
        }
    }

    FloatingWindow {
        id: window
        objectName: "tiddlywikiWindow"
        title: "TiddlyWiki"
        visible: root.opened
        implicitWidth: 820
        implicitHeight: 680
        minimumSize: Qt.size(480, 420)
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
                onEditOpened: root._mode = "edit"
                onCloseRequested: {
                    var wasEditing = editor.editing
                    editor.close()
                    if (wasEditing) {
                        root._mode = "view"
                        search.openTiddler(search.readerTitle)
                    } else root.dismiss()
                }
            }
        }
    }
}
