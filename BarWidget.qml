import QtQuick
import qs.Ui

BarWidget {
    id: root
    moduleName: "rryan.tiddlywiki"
    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight

    WidgetButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        text: "\uf044"
        horizontalMargin: 8
        onPressed: function(mouseButton) {
            if (!root.bar) return
            if (mouseButton === Qt.RightButton)
                root.bar.run("omarchy-shell shell summon rryan.tiddlywiki '{\"mode\":\"settings\"}'")
            else if (mouseButton === Qt.LeftButton)
                root.bar.run("omarchy-shell shell summon rryan.tiddlywiki '{}'")
        }
    }
}
