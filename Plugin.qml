import QtQuick

Item {
    id: root
    objectName: "tiddlywikiPlugin"
    property var shell: null
    property var manifest: null
    property string _mode: "editor"
    readonly property string mode: _mode
    readonly property bool opened: editor.opened || search.opened

    function open(payloadJson) {
        var payload = {}
        try { payload = JSON.parse(payloadJson || "{}") || {} } catch (e) {}
        if (payload.mode === "search") {
            editor.close()
            _mode = "search"
            search.open(payloadJson)
        } else {
            search.close()
            _mode = "editor"
            editor.open(payloadJson)
        }
    }

    function close() {
        search.close()
        editor.close()
    }

    // Both instances stay alive: searching never discards the editor's draft.
    Editor { id: editor; shell: root.shell; manifest: root.manifest }
    Search { id: search; shell: root.shell; manifest: root.manifest }
}
