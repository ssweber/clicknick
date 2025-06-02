Jxon_Dump(obj, indent:="", lvl:=1)
{
	static q := Chr(34)

	if IsObject(obj)
	{
		static Type := Func("Type")
		if Type ? (Type.Call(obj) != "Object") : (ObjGetCapacity(obj) == "")
			throw Exception("Object type not supported.", -1, Format("<Object at 0x{:p}>", &obj))

		is_array := 0
		for k in obj
			is_array := k == A_Index
		until !is_array

		static integer := "integer"
		if indent is %integer%
		{
			if (indent < 0)
				throw Exception("Indent parameter must be a positive integer.", -1, indent)
			spaces := indent, indent := ""
			Loop % spaces
				indent .= " "
		}
		indt := ""
		Loop, % indent ? lvl : 0
			indt .= indent

		lvl += 1, out := "" ; Make #Warn happy
		for k, v in obj
		{
			if IsObject(k) || (k == "")
				throw Exception("Invalid object key.", -1, k ? Format("<Object at 0x{:p}>", &obj) : "<blank>")
			
			if !is_array
				out .= ( ObjGetCapacity([k], 1) ? Jxon_Dump(k) : q . k . q ) ;// key
				    .  ( indent ? ": " : ":" ) ; token + padding
			out .= Jxon_Dump(v, indent, lvl) ; value
			    .  ( indent ? ",`n" . indt : "," ) ; token + indent
		}

		if (out != "")
		{
			out := Trim(out, ",`n" . indent)
			if (indent != "")
				out := "`n" . indt . out . "`n" . SubStr(indt, StrLen(indent)+1)
		}
		
		return is_array ? "[" . out . "]" : "{" . out . "}"
	}

	; Number
	else if (ObjGetCapacity([obj], 1) == "")
		return obj

	; String (null -> not supported by AHK)
	if (obj != "")
	{
		  obj := StrReplace(obj,  "\",    "\\")
		, obj := StrReplace(obj,  "/",    "\/")
		, obj := StrReplace(obj,    q, "\" . q)
		, obj := StrReplace(obj, "`b",    "\b")
		, obj := StrReplace(obj, "`f",    "\f")
		, obj := StrReplace(obj, "`n",    "\n")
		, obj := StrReplace(obj, "`r",    "\r")
		, obj := StrReplace(obj, "`t",    "\t")

		static needle := (A_AhkVersion<"2" ? "O)" : "") . "[^\x20-\x7e]"
		while RegExMatch(obj, needle, m)
			obj := StrReplace(obj, m[0], Format("\u{:04X}", Ord(m[0])))
	}
	
	return q . obj . q
}

AutoExec() {
    BlockInput, Mouse
    CoordMode, Mouse, Screen
    SetDefaultMouseSpeed, 0
    
    ; Delays
    SetControlDelay, 0
    SetMouseDelay, 100
    SetWinDelay, 0
}
    
+`:: ; CTRL ALT S
    IfWinActive, CLICK Programming Software
    {
        Send, !f
        Send, e
        Send, n
    }
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
ControlSetText(control, new_text, win_title) {
    ControlSetText, % control, % new_text, % win_title
}
ControlEnd(control, win_title) {
    ControlSend, % control, ^{End}, % win_title
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
Send(text) {
    Send, % text
}
WinActivate(title) {
    WinActivate, % title
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