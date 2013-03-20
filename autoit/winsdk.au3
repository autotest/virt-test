#cs ---------------------------------------------
AutoIt Version: 3.1.1.0
Author:Feng Yang

Script Function:
autoit script for windwos SDK installation 
#ce ---------------------------------------------

If NOT FileExists("C:\Program Files\Microsoft SDKs\Windows\v7.0\Bin\signtool.exe") Then
    $drive = DriveGetDrive("CDROM")
    For $i = 1 to $drive[0]
        If FileExists($drive[$i] & "\setup.exe") AND  FileExists($drive[$i] & "\winsdk_dvdamd64.msi") Then
            Run($drive[$i] & "\setup.exe")
        EndIf
    Next
    WinWaitActive("[CLASS:WindowsForms10.Window.8.app.0.3fbab22]", "Welcome to the Setup Wizard")
    Send("!n")
    WinWaitActive("[CLASS:WindowsForms10.Window.8.app.0.3fbab22]", "MICROSOFT SOFTWARE LICENSE TERMS")
    Send("!a")
    Send("!n")
    WinWaitActive("[CLASS:WindowsForms10.Window.8.app.0.3fbab22]", "Install Locations")
    Send("!n")
    WinWaitActive("[CLASS:WindowsForms10.Window.8.app.0.3fbab22]", "Installation Options") 
    Send("!n")
    WinWaitActive("[CLASS:WindowsForms10.Window.8.app.0.3fbab22]", "Begin Installation")
    Send("!n")
    WinWaitActive("[CLASS:WindowsForms10.Window.8.app.0.3fbab22]", "Installation Complete")
    Send("{ENTER}")
EndIf
