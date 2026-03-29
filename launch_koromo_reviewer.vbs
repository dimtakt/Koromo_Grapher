Option Explicit

Dim shell
Dim fso
Dim root
Dim exeRelease
Dim exeDist
Dim runnerReleaseDir
Dim runnerReleaseExe
Dim runnerDistDir
Dim runnerDistExe

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(WScript.ScriptFullName)
exeRelease = root & "\release\KoromoGrapher\KoromoGrapher.exe"
runnerReleaseDir = root & "\release\KoromoGrapher\run_local_mortal_review"
runnerReleaseExe = runnerReleaseDir & "\run_local_mortal_review.exe"
exeDist = root & "\dist\KoromoGrapher\KoromoGrapher.exe"
runnerDistDir = root & "\dist\run_local_mortal_review"
runnerDistExe = runnerDistDir & "\run_local_mortal_review.exe"

If fso.FileExists(exeRelease) And fso.FileExists(runnerReleaseExe) Then
  shell.Run """" & exeRelease & """", 1, False
  WScript.Quit 0
End If

If fso.FileExists(exeDist) And fso.FileExists(runnerDistExe) Then
  shell.Run """" & exeDist & """", 1, False
  WScript.Quit 0
End If

MsgBox "KoromoGrapher.exe was not found." & vbCrLf & _
       "A built release is required under release\\KoromoGrapher or dist\\KoromoGrapher.", _
       vbExclamation, "Koromo Grapher"
