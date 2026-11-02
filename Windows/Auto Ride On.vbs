' Starts Auto Ride On with no command window - just the small corner window.
' The main app keeps Zwift connected and reopens the window if it crashes or freezes.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
d = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = d
If Not fso.FileExists(d & "\.venv\Scripts\pythonw.exe") Then
  ' first run only: install the Python package in a visible window
  sh.Run "cmd /c """"" & d & "\Start Auto Ride On.bat"" --setup-only""", 1, True
End If
sh.Run """" & d & "\.venv\Scripts\pythonw.exe"" """ & d & "\auto_rideon_app.pyw""", 0, False
