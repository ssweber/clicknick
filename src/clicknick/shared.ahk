#Include {{LIB_DIRECTORY}}\jxon.ahk

AutoExec() {
    BlockInput, Mouse
    CoordMode, Mouse, Screen
    SetDefaultMouseSpeed, 0
    
    ; Delays
    SetControlDelay, 150
    SetMouseDelay, 100
    SetWinDelay, 200
}

!`:: ; Alt + `
    Process, Close, {{PYTHON_PID}}
    return

ControlGetFocus(win_title) {
    response =
    ControlGetFocus, response, % win_title
    return response
}
ControlFocus(control, win_title) {
    ControlFocus, % control, % win_title
}
ControlGetPos(control, win_title) {
    ControlGetPos, x, y, width, height, % control, % win_title
    return x "," y "," width "," height
}
ControlGetText(control, win_title) {
    response =
    ControlGetText, response, % control, % win_title
    return response
}
ControlSetText(control, new_text, win_title, send_tab) {
    ControlSetText, % control, % new_text, % win_title
    Send, {RIGHT}
    if send_tab
    {
        Send, +{TAB}
    }
}
Paste(sText,restore := True) {
    If (restore)
        ClipBackup:= ClipboardAll
    Clipboard := sText
    SendInput ^v
    If (restore) {
        Sleep, 150
        While DllCall("user32\GetOpenClipboardWindow", "Ptr")
            Sleep, 150
        Clipboard := ClipBackup
    }
}
WinGetClass(title) {
    response =
    WinGetClass, response, % title
    return response
}
WinGetPos(title) {
    WinGetPos, x, y, width, height, % title
    return x "," y "," width "," height
}
WinGet(cmd, title) {
    response =
    WinGet, response, %cmd%, % title
    return response
}
WinGetState(title) {
    response =
    WinGet, response, MinMax, % title
    return response
}
WinGetClick() {
    result := []
    WinGet, id_list, List, ahk_exe Click.exe
    Loop, %id_list%
    {
        this_id := id_list%A_Index%
        WinGetTitle, this_title, ahk_id %this_id%
        
        item := {}
        item.index := A_Index
        item.id := this_id
        item.title := this_title
        
        result.Push(item)
    }
    
    response := Jxon_Dump(result)
    return response
}
WinGetTitle(title) {
    response =
    WinGetTitle, response, % title
    return response
}