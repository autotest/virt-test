#cs ---------------------------------------------
AutoIt Version: 3.1.1.0
Author: Feng Yang

Script Function:
Install qxl driver by scripts.
#ce ---------------------------------------------
Switch int($CmdLine[0])
    case 0
        $FILE="D:\devcon\wnet_amd64\devcon.exe"
        $PARA="install A:\amd64\Win7\qxl.inf PCI\VEN_1b36&DEV_0100"    
        $TITLE="[CLASS:#32770]"
        $TIMEOUT=10
    case 1
        $FILE=$CmdLine[1]
        $PARA="install A:\amd64\Win7\qxl.inf PCI\VEN_1b36&DEV_0100"    
        $TITLE="[CLASS:#32770]"
        $TIMEOUT=10
    case 2
        $FILE=$CmdLine[1]
        $PARA=$CmdLine[2]
        $TITLE="[CLASS:#32770]"
        $TIMEOUT=10
    case 3
        $FILE=$CmdLine[1]
        $PARA=$CmdLine[2]
        $TITLE=$CmdLine[3]
        $TIMEOUT=10
    case 4
        $FILE=$CmdLine[1]
        $PARA=$CmdLine[2]
        $TITLE=$CmdLine[3]
        $TIMEOUT=$CmdLine[4]
EndSwitch
$PARA = StringReplace($PARA, ";", "")
ShellExecute($FILE, $PARA, "", "")
WinWaitActive($TITLE, "", $TIMEOUT)
Send("!i")
