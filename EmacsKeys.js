.pragma library

var ring = []
var previous = null
var yank = null

function before(text, p) {
    if (p > 1 && /[\uDC00-\uDFFF]/.test(text[p-1]) && /[\uD800-\uDBFF]/.test(text[p-2])) return p-2
    return Math.max(0, p-1)
}
function after(text, p) {
    if (p+1 < text.length && /[\uD800-\uDBFF]/.test(text[p]) && /[\uDC00-\uDFFF]/.test(text[p+1])) return p+2
    return Math.min(text.length, p+1)
}
function word(c) {
    return c && !/[\s.,;:!?()[\]{}<>/"'`~@#$%^&*+=\\|–—-]/.test(c)
}
function wordBoundary(text, p, direction) {
    if (direction > 0) {
        while (p < text.length && !word(text[p])) p = after(text, p)
        while (p < text.length && word(text[p])) p = after(text, p)
    } else {
        while (p > 0 && !word(text[before(text,p)])) p = before(text,p)
        while (p > 0 && word(text[before(text,p)])) p = before(text,p)
    }
    return p
}
function erase(control, start, end, kill, backward) {
    if (start === end) return
    var removed = control.text.slice(start,end)
    if (kill) {
        if (previous && previous.control === control && previous.text === control.text
                && previous.cursor === control.cursorPosition && control.selectionStart === control.selectionEnd) {
            ring[0] = backward ? removed + ring[0] : ring[0] + removed
        } else {
            ring.unshift(removed)
            if (ring.length > 32) ring.pop()
        }
    }
    control.remove(start,end)
    control.cursorPosition = start
    previous = kill ? {control:control,text:control.text,cursor:start} : null
}
function handle(control, event, state) {
    var ctrl = event.modifiers === Qt.ControlModifier
    var alt = event.modifiers === Qt.AltModifier
    var key = event.key
    // Modifier presses must not break vertical movement or consecutive kills.
    if (key === Qt.Key_Control || key === Qt.Key_Shift || key === Qt.Key_Alt
            || key === Qt.Key_Meta || key === Qt.Key_AltGr) return false
    var text = control.text
    var p = control.cursorPosition
    var destination = -1
    var start = p
    var end = p
    var kill = false
    var backward = false
    var vertical = false
    if (ctrl && key === Qt.Key_A) destination = p === 0 ? 0 : text.lastIndexOf('\n',p-1)+1
    else if (ctrl && key === Qt.Key_E) { destination = text.indexOf('\n',p); if (destination < 0) destination = text.length }
    else if (ctrl && key === Qt.Key_B) destination = before(text,p)
    else if (ctrl && key === Qt.Key_F) destination = after(text,p)
    else if (alt && key === Qt.Key_B) destination = wordBoundary(text,p,-1)
    else if (alt && key === Qt.Key_F) destination = wordBoundary(text,p,1)
    else if (ctrl && (key === Qt.Key_P || key === Qt.Key_N)) {
        vertical = true
        if (state.multiline) {
            var rect = control.cursorRectangle
            if (state.goalX < 0 || state.verticalPosition !== p || state.verticalText !== text)
                state.goalX = rect.x
            destination = control.positionAt(state.goalX,rect.y + rect.height*(key === Qt.Key_P ? -0.5 : 1.5))
        } else destination = p
    } else if (ctrl && (key === Qt.Key_D || key === Qt.Key_H)) {
        backward = key === Qt.Key_H
        start = backward ? before(text,p) : p
        end = backward ? p : after(text,p)
    } else if (ctrl && key === Qt.Key_K) {
        kill = true
        end = text.indexOf('\n',p)
        if (end < 0) end = text.length
        else if (end === p) end = p+1
    } else if (ctrl && key === Qt.Key_U) {
        kill = true; backward = true
        start = p === 0 ? 0 : text.lastIndexOf('\n',p-1)+1
    } else if ((alt && key === Qt.Key_D) || (alt && key === Qt.Key_Backspace) || (ctrl && key === Qt.Key_W)) {
        kill = true
        backward = key !== Qt.Key_D
        start = backward ? wordBoundary(text,p,-1) : p
        end = backward ? p : wordBoundary(text,p,1)
    } else if (ctrl && key === Qt.Key_Y) {
        previous = null; state.goalX = -1
        if (control.readOnly || !ring.length) return true
        start = control.selectionStart; end = control.selectionEnd
        control.remove(start,end)
        control.insert(start,ring[0])
        control.cursorPosition = start+ring[0].length
        yank = {control:control,start:start,end:control.cursorPosition,index:0,text:control.text}
        return true
    } else if (alt && key === Qt.Key_Y) {
        previous = null; state.goalX = -1
        if (!control.readOnly && yank && yank.control === control && yank.text === text && yank.end === p && ring.length) {
            yank.index = (yank.index+1)%ring.length
            control.remove(yank.start,yank.end)
            control.insert(yank.start,ring[yank.index])
            yank.end = yank.start+ring[yank.index].length
            control.cursorPosition = yank.end
            yank.text = control.text
        }
        return true
    } else {
        previous = null; yank = null; state.goalX = -1
        return false
    }
    yank = null
    if (!vertical) state.goalX = -1
    if (destination >= 0) {
        previous = null
        control.deselect()
        control.cursorPosition = destination
        if (vertical) {
            state.verticalPosition = destination
            state.verticalText = text
        }
    } else if (!control.readOnly) {
        if (control.selectionStart !== control.selectionEnd) { start = control.selectionStart; end = control.selectionEnd }
        erase(control,start,end,kill,backward)
    }
    return true
}
