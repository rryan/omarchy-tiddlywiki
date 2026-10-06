import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import Quickshell.Io
import qs.Commons

Item {
    id: root
    objectName: "tiddlywikiSettings"
    property bool opened: false
    property bool hasDrafts: false
    property bool saving: false
    readonly property bool confirmationPending: !!discardLoader.item && discardLoader.item.visible
    property bool loading: false
    property bool _readReady: false
    property bool _hasPassword: false
    property bool _failed: false
    property string _message: ""
    property string _baselineUrl: ""
    property string _baselineUsername: ""
    property int _generation: 0
    property bool _readQueued: false
    property string _savePayload: ""
    signal saved(bool connectionChanged)
    signal closeRequested()

    function normalizedUrl(value) {
        return value.trim().replace(/^([a-z][a-z0-9+.-]*):\/\/([^/?#]*)/i, function(match, scheme, authority) {
            return scheme.toLowerCase() + "://" + authority.toLowerCase()
        }).replace(/\/+$/, "")
    }
    function connectionChanged() {
        return normalizedUrl(urlField.text) !== normalizedUrl(_baselineUrl)
            || usernameField.text !== _baselineUsername
    }
    function closeConfirmation() {
        if (discardLoader.item) discardLoader.item.close()
        discardLoader.active = false
    }
    function open() {
        if (saving) return false
        closeConfirmation()
        ++_generation
        opened = true
        passwordField.clear()
        urlField.clear()
        usernameField.clear()
        _baselineUrl = ""
        _baselineUsername = ""
        _hasPassword = false
        _readReady = false
        _failed = false
        _message = "Loading connection settings…"
        loading = true
        if (readProcess.running) _readQueued = true
        else beginRead()
        return true
    }
    function beginRead() {
        _readQueued = false
        readProcess.generation = _generation
        readProcess.received = false
        readProcess.result = null
        readProcess.running = true
    }
    function close() {
        if (saving) return false
        ++_generation
        opened = false
        loading = false
        _readQueued = false
        _readReady = false
        passwordField.clear()
        _savePayload = ""
        closeConfirmation()
        return true
    }
    function requestClose() {
        if (!saving && !confirmationPending) {
            close()
            closeRequested()
        }
    }
    function save() {
        if (!opened || saving || loading || !_readReady || confirmationPending) return
        _failed = false
        _message = ""
        if (hasDrafts && connectionChanged()) {
            discardLoader.active = true
            discardLoader.item.open()
            return
        }
        beginSave()
    }
    function beginSave() {
        if (!opened || saving || !_readReady) return
        _savePayload = JSON.stringify({url: urlField.text.trim(), username: usernameField.text,
            password: passwordField.text})
        saveProcess.generation = _generation
        saveProcess.received = false
        saveProcess.result = null
        saving = true
        _failed = false
        _message = "Saving connection settings…"
        saveProcess.running = true
    }
    function receiveRead(line) {
        if (readProcess.received || readProcess.generation !== _generation || !opened) return
        readProcess.received = true
        try { readProcess.result = JSON.parse(line) } catch (e) { readProcess.result = null }
    }
    function finishRead(exitCode) {
        if (readProcess.generation === _generation && opened) {
            loading = false
            var result = readProcess.result
            if (exitCode === 0 && result && result.ok === true
                    && typeof result.url === "string" && typeof result.username === "string"
                    && typeof result.hasPassword === "boolean") {
                _baselineUrl = result.url
                _baselineUsername = result.username
                _hasPassword = result.hasPassword
                urlField.text = result.url
                usernameField.text = result.username
                _readReady = true
                _message = ""
                _failed = false
                Qt.callLater(function() {
                    if (root.opened && root.visible && root._readReady) urlField.forceActiveFocus()
                })
            } else {
                _readReady = false
                _failed = true
                _message = result && typeof result.error === "string" ? result.error
                    : "Could not read connection settings. Close and reopen settings to try again."
            }
        }
        readProcess.result = null
        if (_readQueued && opened) beginRead()
    }
    function receiveSave(line) {
        if (saveProcess.received || saveProcess.generation !== _generation || !opened) return
        saveProcess.received = true
        try { saveProcess.result = JSON.parse(line) } catch (e) { saveProcess.result = null }
    }
    function finishSave(exitCode) {
        saving = false
        _savePayload = ""
        if (saveProcess.generation !== _generation || !opened) {
            saveProcess.result = null
            return
        }
        var result = saveProcess.result
        saveProcess.result = null
        if (exitCode === 0 && result && result.ok === true
                && typeof result.connectionChanged === "boolean") {
            passwordField.clear()
            _failed = false
            _message = ""
            close()
            saved(result.connectionChanged)
        } else {
            _failed = true
            _message = result && typeof result.error === "string" ? result.error
                : "Could not save connection settings. Your entries and retained drafts have been kept."
        }
    }

    Process {
        id: readProcess
        property int generation: -1
        property bool received: false
        property var result: null
        command: ["python3", Qt.resolvedUrl("tiddlywiki.py").toString().replace(/^file:\/\//, ""), "settings-read"]
        stdinEnabled: true
        onStarted: write("{}\n")
        stdout: SplitParser { onRead: function(line) { root.receiveRead(line) } }
        onExited: function(exitCode, exitStatus) { root.finishRead(exitCode) }
    }
    Process {
        id: saveProcess
        property int generation: -1
        property bool received: false
        property var result: null
        command: ["python3", Qt.resolvedUrl("tiddlywiki.py").toString().replace(/^file:\/\//, ""), "settings-save"]
        stdinEnabled: true
        onStarted: {
            write(root._savePayload + "\n")
            root._savePayload = ""
        }
        stdout: SplitParser { onRead: function(line) { root.receiveSave(line) } }
        onExited: function(exitCode, exitStatus) { root.finishSave(exitCode) }
    }

    Loader {
        id: discardLoader
        active: false
        sourceComponent: Component {
            Dialog {
                id: discardDialog
                objectName: "tiddlywikiDiscardConnection"
                parent: root.Window.window.contentItem
                x: Math.max(0, (parent.width - width) / 2)
                y: Math.max(0, (parent.height - height) / 2)
                width: Math.max(0, Math.min(440, parent.width - 32))
                modal: true
                title: "Change connection?"
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
                    text: "Changing the connection will discard this session's retained drafts only if the new settings are saved successfully. Discard drafts and save the new connection? Cancel keeps your settings entries and drafts."
                    color: Color.menu.text
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                }
                onDiscarded: {
                    discardDialog.close()
                    root.beginSave()
                }
            }
        }
    }

    Shortcut {
        sequence: "Escape"
        enabled: root.opened && root.visible && !root.saving && !root.confirmationPending
        onActivated: root.requestClose()
    }
    Shortcut {
        sequence: "Ctrl+Return"
        enabled: root.opened && root.visible && root._readReady && !root.saving && !root.confirmationPending
        onActivated: root.save()
    }

    ScrollView {
        id: formScroll
        anchors.fill: parent
        anchors.margins: Math.min(24, root.width / 12)
        contentWidth: availableWidth
        clip: true
        ColumnLayout {
            width: formScroll.availableWidth
            spacing: 10
            Label {
                Layout.fillWidth: true
                text: "Connection settings"
                color: Color.menu.text
                font.pixelSize: 24
                font.bold: true
                wrapMode: Text.Wrap
            }
            Label {
                Layout.fillWidth: true
                text: "Connect to a TiddlyWiki hosted on Node.js. These credentials are for the server's HTTP Basic Authentication, not a separate wiki login."
                textFormat: Text.PlainText
                color: Color.menu.text
                wrapMode: Text.Wrap
            }
            Label { text: "Wiki root URL"; color: Color.menu.text }
            TextField {
                id: urlField
                objectName: "settingsUrl"
                Layout.fillWidth: true
                placeholderText: "https://wiki.example.com"
                enabled: root._readReady && !root.saving && !root.confirmationPending
                selectByMouse: true
                inputMethodHints: Qt.ImhUrlCharactersOnly | Qt.ImhNoAutoUppercase
                EmacsInput { control: urlField }
                KeyNavigation.tab: usernameField
            }
            Label {
                Layout.fillWidth: true
                text: "Use the wiki's root address, without a query or fragment. HTTPS is required, except HTTP is allowed for localhost, 127.0.0.1, or [::1] on this computer."
                textFormat: Text.PlainText
                color: Color.menu.text
                wrapMode: Text.Wrap
            }
            Label {
                Layout.fillWidth: true
                text: "HTTP Basic username"
                color: Color.menu.text
                wrapMode: Text.Wrap
            }
            TextField {
                id: usernameField
                objectName: "settingsUsername"
                Layout.fillWidth: true
                placeholderText: "Server username"
                enabled: root._readReady && !root.saving && !root.confirmationPending
                selectByMouse: true
                inputMethodHints: Qt.ImhNoAutoUppercase | Qt.ImhNoPredictiveText
                EmacsInput { control: usernameField }
                KeyNavigation.tab: passwordField
                KeyNavigation.backtab: urlField
            }
            Label {
                Layout.fillWidth: true
                text: "HTTP Basic password"
                color: Color.menu.text
                wrapMode: Text.Wrap
            }
            TextField {
                id: passwordField
                objectName: "settingsPassword"
                Layout.fillWidth: true
                placeholderText: root._hasPassword && !root.connectionChanged() ? "Leave blank to keep the saved password" : "Server password"
                echoMode: TextInput.Password
                enabled: root._readReady && !root.saving && !root.confirmationPending
                selectByMouse: true
                inputMethodHints: Qt.ImhSensitiveData | Qt.ImhHiddenText | Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase
                KeyNavigation.backtab: usernameField
                KeyNavigation.tab: saveButton
            }
            Label {
                Layout.fillWidth: true
                text: root._hasPassword && !root.connectionChanged()
                    ? "A password is saved. Leave this field blank to keep it for the same URL and username."
                    : "Enter a password for this connection. A saved password cannot be reused when the URL or username changes."
                textFormat: Text.PlainText
                color: Color.menu.text
                wrapMode: Text.Wrap
            }
            Label {
                Layout.fillWidth: true
                visible: !!root._message
                text: root._message
                textFormat: Text.PlainText
                color: root._failed ? "#ef8080" : Color.menu.text
                wrapMode: Text.Wrap
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 8
                Item { Layout.fillWidth: true }
                Button {
                    text: "Cancel"
                    enabled: !root.saving && !root.confirmationPending
                    onClicked: root.requestClose()
                }
                Button {
                    id: saveButton
                    objectName: "saveSettings"
                    text: root.saving ? "Saving…" : "Save"
                    highlighted: true
                    enabled: root._readReady && !root.loading && !root.saving && !root.confirmationPending
                    onClicked: root.save()
                }
            }
        }
    }
}
