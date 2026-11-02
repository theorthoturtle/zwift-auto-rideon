' Puts an "Auto Ride On" shortcut (with its icon) on your desktop. Run once.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
d = fso.GetParentFolderName(WScript.ScriptFullName)
Set lnk = sh.CreateShortcut(sh.SpecialFolders("Desktop") & "\Auto Ride On.lnk")
lnk.TargetPath = sh.ExpandEnvironmentStrings("%WINDIR%") & "\System32\wscript.exe"
lnk.Arguments = """" & d & "\Auto Ride On.vbs"""
lnk.WorkingDirectory = d
lnk.IconLocation = d & "\auto_rideon.ico, 0"
lnk.Description = "Auto Ride On for Zwift"
lnk.Save
MsgBox "Added ""Auto Ride On"" to your desktop.", 64, "Auto Ride On"
