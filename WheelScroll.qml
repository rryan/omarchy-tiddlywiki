import QtQuick

// Scale wheel distance only; compositor touchpad momentum and native touch flicks stay native.
Item {
    id: root
    required property Flickable scroller
    property real sensitivity: 2
    property real wheelStep: 96

    function bounded(value) {
        var minimum = scroller.originY
        var maximum = minimum + Math.max(0, scroller.contentHeight - scroller.height)
        return Math.max(minimum, Math.min(maximum, value))
    }

    function constrain() {
        var current = bounded(scroller.contentY)
        if (current !== scroller.contentY) scroller.contentY = current
    }

    WheelHandler {
        parent: root.scroller
        target: null
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        onWheel: function(event) {
            var pixels = event.pixelDelta.y
            var angle = event.angleDelta.y
            if (!pixels && !angle) {
                event.accepted = false
                return
            }
            root.scroller.cancelFlick()
            root.scroller.contentY = root.bounded(root.scroller.contentY
                - (pixels || angle / 120 * root.wheelStep) * root.sensitivity)
            event.accepted = true
        }
    }

    Connections {
        target: root.scroller
        function onContentHeightChanged() { root.constrain() }
        function onHeightChanged() { root.constrain() }
        function onOriginYChanged() { root.constrain() }
    }
}
