import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import Quickshell.Io
import qs.Commons

Item {
    id: root
    objectName: "tiddlywikiEditor"
    property var context: []
    property bool opened: false
    property bool editing: false
    property bool saving: false
    property string message: ""
    property bool failed: false
    property var _createDraft: emptyDraft()
    property var _editDraft: null
    property var _preparedDrafts: ({})
    property string _preparedKey: ""
    property var _pendingPrepared: null
    property var _original: null
    property string _baseline: ""
    property var _pendingEdit: null
    property bool _draftSaved: false
    property string _savePayload: ""
    property string _saveAction: "create"
    property bool _saveReceived: false
    readonly property bool confirmationPending: !!discardLoader.item && discardLoader.item.visible
    readonly property bool dirty: editing && draftKey(currentDraft()) !== _baseline
    signal savedTiddler(string title)
    signal closeRequested()
    signal editOpened()
    signal preparedOpened(string mode, string title)
    signal preparedCancelled()

    function emptyDraft() {
        return {title: "", text: "", tags: "", type: "text/x-markdown", message: "", failed: false}
    }
    function currentDraft() {
        return {title: titleField.text, text: bodyField.text, tags: tagsField.text,
            type: typeField.editText, message: message, failed: failed}
    }
    function draftKey(draft) {
        return JSON.stringify([draft.title, draft.text, draft.tags, draft.type])
    }
    function retainDraft() {
        if (_draftSaved) return
        if (editing) _editDraft = currentDraft()
        else if (_preparedKey) _preparedDrafts[_preparedKey] = currentDraft()
        else _createDraft = currentDraft()
    }
    function showDraft(draft) {
        _draftSaved = false
        titleField.text = draft.title
        bodyField.text = draft.text
        tagsField.text = draft.tags
        typeField.editText = draft.type
        message = draft.message || ""
        failed = draft.failed === true
        opened = true
        Qt.callLater(function() {
            if (root.opened && root.visible) {
                if (root.editing) bodyField.forceActiveFocus()
                else titleField.forceActiveFocus()
            }
        })
    }
    function sameOriginal(fields) {
        if (!_original) return false
        var keys = Object.keys(_original)
        if (keys.length !== Object.keys(fields).length) return false
        for (var i = 0; i < keys.length; ++i) {
            if (JSON.stringify(_original[keys[i]]) !== JSON.stringify(fields[keys[i]])) return false
        }
        return true
    }
    function closeConfirmation() {
        if (discardLoader.item) discardLoader.item.close()
        discardLoader.active = false
    }
    function open(payloadJson) {
        if (saving) return false
        closeConfirmation()
        _pendingEdit = null
        _pendingPrepared = null
        retainDraft()
        _preparedKey = ""
        editing = false
        showDraft(_createDraft)
        return true
    }
    function formattedTags(tags) {
        return Array.isArray(tags) ? tags.map(function(tag) {
            return /\s/.test(tag) ? "[[" + tag + "]]" : tag
        }).join(" ") : String(tags || "")
    }
    function applyPrepared(prepared, restored) {
        if (!prepared) return
        if (restored) {
            // Preserve the editable draft rather than replacing it with server tags.
            var tags = tagsField.text.match(/\[\[[\s\S]*?\]\]|[^\s]+/g) || []
            var requiredTag = prepared.kind === "today" ? "Journal" : "Note"
            if (!tags.some(function(tag) { return tag === requiredTag || tag === "[[" + requiredTag + "]]" }))
                tagsField.text += (tagsField.text && !/\s$/.test(tagsField.text) ? " " : "") + requiredTag
        } else {
            tagsField.text = formattedTags(prepared.tags)
        }
        retainDraft()
        preparedOpened(prepared.mode, titleField.text)
    }
    function openPrepared(result) {
        if (saving || !result || result.ok !== true || !result.fields
                || (result.kind !== "today" && result.kind !== "quick-note")
                || typeof result.date !== "string" || !Array.isArray(result.tags)
                || typeof result.fields.title !== "string") return false
        if (result.mode === "edit") return openForEdit(result.fields, result)
        if (result.mode !== "create") return false
        closeConfirmation()
        _pendingEdit = null
        _pendingPrepared = null
        retainDraft()
        _preparedKey = result.kind + ":" + result.date
        editing = false
        var draft = _preparedDrafts[_preparedKey]
        var restored = !!draft
        if (!draft) {
            draft = {title: result.fields.title, text: String(result.fields.text || ""),
                tags: formattedTags(result.tags), type: String(result.fields.type || "text/x-markdown"),
                message: "", failed: false}
        }
        showDraft(draft)
        applyPrepared(result, restored)
        return true
    }
    function openForEdit(fields, prepared) {
        if (saving || !fields || typeof fields.title !== "string") return false
        closeConfirmation()
        _pendingEdit = null
        _pendingPrepared = null
        retainDraft()
        if (_editDraft && _original && _original.title === fields.title && sameOriginal(fields)) {
            _preparedKey = ""
            editing = true
            showDraft(_editDraft)
            applyPrepared(prepared, true)
            return true
        }
        if (_editDraft && draftKey(_editDraft) !== _baseline) {
            _pendingEdit = JSON.parse(JSON.stringify(fields))
            _pendingPrepared = prepared || null
            discardLoader.active = true
            discardLoader.item.open()
            return false
        }
        beginEdit(fields, prepared)
        return true
    }
    function beginEdit(fields, prepared) {
        _original = JSON.parse(JSON.stringify(fields))
        _editDraft = {title: fields.title, text: String(fields.text || ""), tags: formattedTags(fields.tags),
            type: String(fields.type || "text/vnd.tiddlywiki"), message: "", failed: false}
        _baseline = draftKey(_editDraft)
        _preparedKey = ""
        editing = true
        showDraft(_editDraft)
        applyPrepared(prepared, false)
    }
    function close() {
        retainDraft()
        opened = false
        closeConfirmation()
        _pendingEdit = null
        _pendingPrepared = null
    }
    function requestClose() {
        retainDraft()
        closeRequested()
    }
    function save() {
        if (saving) return
        if (!titleField.text.trim()) {
            failed = true
            message = "Enter a title."
            titleField.forceActiveFocus()
            return
        }
        var payload = {title: titleField.text, tags: tagsField.text,
            text: bodyField.text, type: typeField.editText}
        if (editing) payload.original = _original
        _saveAction = editing ? "update" : "create"
        _savePayload = JSON.stringify(payload)
        _saveReceived = false
        message = "Saving…"
        failed = false
        saving = true
        saveProcess.running = true
    }
    function saved(line) {
        if (_saveReceived) return
        _saveReceived = true
        var result
        try { result = JSON.parse(line) } catch (e) {
            failed = true
            message = "Invalid save response. Draft retained; check the wiki before retrying."
            retainDraft()
            return
        }
        if (!result || result.ok !== true || typeof result.title !== "string") {
            failed = true
            message = result && typeof result.error === "string" ? result.error
                : "Save failed. Draft retained; check the wiki before retrying."
            retainDraft()
            return
        }
        failed = false
        message = "Saved “" + result.title + "”."
        if (_saveAction === "update") {
            _editDraft = null
            _original = null
            _baseline = ""
        } else if (_preparedKey) delete _preparedDrafts[_preparedKey]
        else _createDraft = emptyDraft()
        _draftSaved = true
        opened = false
        // Clear only the saved draft. The other mode's retained draft remains untouched.
        titleField.clear()
        bodyField.clear()
        tagsField.clear()
        typeField.editText = "text/x-markdown"
        savedTiddler(result.title)
    }

    Process {
        id: saveProcess
        command: ["python3", Qt.resolvedUrl("tiddlywiki.py").toString().replace(/^file:\/\//, ""), root._saveAction]
        stdinEnabled: true
        onStarted: {
            write(root._savePayload + "\n")
            root._savePayload = ""
        }
        stdout: SplitParser { onRead: function(line) { root.saved(line) } }
        onExited: function(exitCode, exitStatus) {
            root.saving = false
            if (!root._saveReceived) {
                root.failed = true
                root.message = "Save process stopped without a result. Draft retained; check the wiki before retrying."
                root.retainDraft()
            }
        }
    }

    Loader {
        id: discardLoader
        active: false
        // Construct only after the main window has a stable content geometry.
        sourceComponent: Component {
            Dialog {
                id: discardDialog
                objectName: "tiddlywikiDiscardEdit"
                parent: root.Window.window.contentItem
                x: Math.max(0, (parent.width - width) / 2)
                y: Math.max(0, (parent.height - height) / 2)
                width: Math.min(440, parent.width - 32)
                modal: true
                title: "Discard pending edit?"
                standardButtons: Dialog.Discard | Dialog.Cancel
                palette.window: Color.menu.background
                palette.text: Color.menu.text
                palette.windowText: Color.menu.text
                palette.buttonText: Color.menu.text
                palette.button: Color.menu.selectedBackground
                background: Rectangle {
                    color: Color.menu.background
                    border.color: Color.menu.border
                    radius: 8
                }
                contentItem: Text {
                    text: root._pendingEdit && root._original && root._pendingEdit.title === root._original.title
                        ? "The wiki changed since this draft was opened. Discard the retained edit and reload current fields? Your creation draft will be kept."
                        : "Opening another tiddler will discard your unsaved edit. Your creation draft will be kept."
                    color: Color.menu.text
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                }
                onDiscarded: {
                    var fields = root._pendingEdit
                    var prepared = root._pendingPrepared
                    root._pendingEdit = null
                    root._pendingPrepared = null
                    discardDialog.close()
                    if (fields) {
                        root.retainDraft()
                        root.beginEdit(fields, prepared)
                        root.editOpened()
                    }
                }
                onRejected: {
                    var prepared = root._pendingPrepared
                    var resume = root._pendingEdit && root._original
                        && root._pendingEdit.title === root._original.title
                    root._pendingEdit = null
                    root._pendingPrepared = null
                    if (resume) {
                        root.retainDraft()
                        root.editing = true
                        root._preparedKey = ""
                        root.showDraft(root._editDraft)
                        root.applyPrepared(prepared, true)
                        root.editOpened()
                    } else if (prepared) root.preparedCancelled()
                }
            }
        }
    }


    RowLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 24
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: 1
            spacing: 8
        Shortcut { sequence: "Ctrl+Return"; enabled: root.opened && root.visible && !root.saving && !root.confirmationPending; onActivated: root.save() }
        Shortcut { sequence: "Escape"; enabled: root.opened && root.visible && !root.confirmationPending; onActivated: root.requestClose() }

        Label {
            text: root.editing ? "Edit tiddler" : "Create tiddler"
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
            readOnly: root.editing
            selectByMouse: true
            EmacsInput { control: titleField }
            KeyNavigation.tab: bodyField
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
                EmacsInput { control: bodyField; multiline: true }
                KeyNavigation.tab: tagsField
                KeyNavigation.backtab: titleField
                KeyNavigation.priority: KeyNavigation.BeforeItem
            }
        }
        ColumnLayout {
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
                    EmacsInput { control: tagsField }
                    KeyNavigation.tab: typeField
                    KeyNavigation.backtab: bodyField
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Label { text: "Type"; color: Color.menu.text }
                ComboBox {
                    id: typeField
                    objectName: "tiddlerType"
                    Layout.fillWidth: true
                    editable: true
                    model: ["text/x-markdown", "text/markdown", "text/vnd.tiddlywiki", "text/plain", "text/html"]
                    enabled: !root.saving
                    EmacsInput { control: typeField.contentItem }
                    KeyNavigation.backtab: tagsField
                }
            }
        }
        Label {
            Layout.fillWidth: true
            text: root.message || "Back keeps your draft until the shell reloads."
            textFormat: Text.PlainText
            color: root.failed ? "#ef8080" : Color.menu.text
            wrapMode: Text.Wrap
        }
        RowLayout {
            Layout.alignment: Qt.AlignRight
            Button { text: "Back"; onClicked: root.requestClose() }
            Button {
                objectName: "saveTiddler"
                text: root.saving ? "Saving…" : "Save"
                enabled: !root.saving
                highlighted: true
                onClicked: root.save()
            }
        }
    }
        MarkdownPreview {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: 1
            visible: markdown
            active: root.opened && root.visible
            draftTitle: titleField.text
            draftText: bodyField.text
            draftTags: tagsField.text
            draftType: typeField.editText
            context: root.context
        }
    }
}
