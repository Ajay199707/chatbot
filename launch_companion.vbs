' Launches the Always-On-Screen Desktop AI Character silently (no console window)
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
rootExe = baseDir & "\AICompanion.exe"
distExe = baseDir & "\dist\AICompanion.exe"
venvPyw = baseDir & "\.venv\Scripts\pythonw.exe"
scriptPath = baseDir & "\desktop_companion.py"

shell.CurrentDirectory = baseDir

If fso.FileExists(rootExe) Then
    shell.Run """" & rootExe & """", 1, False
ElseIf fso.FileExists(distExe) Then
    shell.Run """" & distExe & """", 1, False
Else
    If fso.FileExists(venvPyw) Then
        pythonExe = """" & venvPyw & """"
    Else
        pythonExe = "pythonw"
    End If
    shell.Run pythonExe & " """ & scriptPath & """", 0, False
End If
