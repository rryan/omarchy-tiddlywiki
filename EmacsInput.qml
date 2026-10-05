import QtQuick
import "EmacsKeys.js" as EmacsKeys

Item {
    id: root
    required property var control
    property bool multiline: false
    property real goalX: -1
    property int verticalPosition: -1
    property string verticalText: ""
    Component.onCompleted: {
        control.Keys.priority = Keys.BeforeItem
        control.Keys.forwardTo = [root]
    }
    Keys.onPressed: function(event) {
        if (EmacsKeys.handle(control, event, root)) event.accepted = true
    }
}
