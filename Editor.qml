import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons

Item {
    id: root
    property var shell: null
    property var manifest: null
    property bool opened: false
    property bool saving: false
    property string message: ""
    property bool failed: false
    property string pendingDraft: ""

    function open(payloadJson) {
        opened = true
        Qt.callLater(function() { titleField.forceActiveFocus() })
    }
    function close() { opened = false }
    function dismiss() {
        opened = false
        if (shell) shell.hide("rryan.tiddlywiki")
    }
    function save() {
        if (saving) return
        if (!titleField.text.trim()) {
            failed = true
            message = "Enter a title."
            titleField.forceActiveFocus()
            return
        }
        message = "Saving…"
        failed = false
        pendingDraft = JSON.stringify({title: titleField.text, tags: tagsField.text,
            text: bodyField.text, type: typeField.editText})
        saving = true
        saveProcess.running = true
    }
    function saved(line) {
        var result
        try { result = JSON.parse(line) } catch (e) {
            failed = true
            message = "Invalid save response. Draft retained; check the wiki before retrying."
            return
        }
        failed = !result.ok
        message = result.ok ? "Saved “" + result.title + "”." : result.error
        if (result.ok) {
            titleField.clear()
            tagsField.clear()
            bodyField.clear()
            typeField.editText = "text/x-markdown"
            titleField.forceActiveFocus()
        }
    }

    Process {
        id: saveProcess
        command: ["python3", Qt.resolvedUrl("tiddlywiki.py").toString().replace(/^file:\/\//, "")]
        stdinEnabled: true
        onStarted: {
            write(root.pendingDraft + "\n")
            root.pendingDraft = ""
        }
        stdout: SplitParser { onRead: function(line) { root.saved(line) } }
        onExited: function(exitCode, exitStatus) {
            root.saving = false
            if (root.message === "Saving…") {
                root.failed = true
                root.message = "Save process stopped without a result. Draft retained; check the wiki before retrying."
            }
        }
    }

    FloatingWindow {
        id: window
        visible: root.opened
        title: "Create tiddler — TiddlyWiki"
        implicitWidth: 780
        implicitHeight: 620
        minimumSize: Qt.size(480, 420)
        color: Color.menu.background
        onVisibleChanged: if (!visible && root.opened) root.dismiss()

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: 12

            Label {
                text: "Create tiddler"
                color: Color.menu.text
                font.pixelSize: 24
                font.bold: true
            }
            Label { text: "Title"; color: Color.menu.text }
            TextField {
                id: titleField
                objectName: "tiddlerTitle"
                Layout.fillWidth: true
                placeholderText: "Tiddler title"
                enabled: !root.saving
                selectByMouse: true
            }
            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    Layout.fillWidth: true
                    Label { text: "Tags"; color: Color.menu.text }
                    TextField {
                        id: tagsField
                        objectName: "tiddlerTags"
                        Layout.fillWidth: true
                        placeholderText: "tag [[multi word tag]]"
                        enabled: !root.saving
                        selectByMouse: true
                    }
                }
                ColumnLayout {
                    Label { text: "Type"; color: Color.menu.text }
                    ComboBox {
                        id: typeField
                        objectName: "tiddlerType"
                        Layout.preferredWidth: 225
                        editable: true
                        model: ["text/x-markdown", "text/vnd.tiddlywiki", "text/plain", "text/html"]
                        enabled: !root.saving
                    }
                }
            }
            Label { text: "Body"; color: Color.menu.text }
            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                TextArea {
                    id: bodyField
                    objectName: "tiddlerBody"
                    placeholderText: "Write your post…"
                    wrapMode: TextEdit.Wrap
                    selectByMouse: true
                    enabled: !root.saving
                }
            }
            Label {
                Layout.fillWidth: true
                text: root.message || "Closing this window keeps your draft until the shell reloads."
                color: root.failed ? "#ef8080" : Color.menu.text
                wrapMode: Text.Wrap
            }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                Button { text: "Close"; onClicked: root.dismiss() }
                Button {
                    objectName: "saveTiddler"
                    text: root.saving ? "Saving…" : "Save"
                    enabled: !root.saving
                    highlighted: true
                    onClicked: root.save()
                }
            }
        }
        Shortcut { sequence: "Ctrl+Return"; enabled: root.opened && !root.saving; onActivated: root.save() }
        Shortcut { sequence: "Escape"; enabled: root.opened; onActivated: root.dismiss() }
    }
}
