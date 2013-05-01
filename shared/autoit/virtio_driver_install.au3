#cs ---------------------------------------------
AutoIt Version: 3.3.8.1
Author: Yiqiao Pu

Script Function:
Install driver by scripts without signature.
#ce ---------------------------------------------
;Default value for the parameters
$FILE="D:\devcon\wnet_amd64\devcon.exe"
$PARA="install A:\amd64\Win7\qxl.inf PCI\VEN_1b36&DEV_0100"    
$TITLE="[CLASS:#32770]"
$TIMEOUT=10


$start_para = False
$para_index = 1
For $i = 1 To $CmdLine[0] Step 1
	if $CmdLine[$i] == "'" Then
	   If $start_para == False Then
		  $start_para = True
		  $tmp_string = ""
	   Else
		  $start_para = False
		  Set_Para($para_index, $tmp_string)
		  $para_index += 1
	   EndIf
	Else
	   if $start_para == True Then
		  $tmp_string &= " "
		  $tmp_string &= $CmdLine[$i]
	   Else
		  Set_Para($para_index, $CmdLine[$i])
		  $para_index += 1
	   EndIf
	EndIf
 Next

$PARA = StringReplace($PARA, ";", "")
ShellExecute($FILE, $PARA, "", "")
WinWaitActive($TITLE, "", $TIMEOUT)
Send("!i")

Func Set_Para($index, $context)
   Switch $index
    case 1
        $FILE=$context
	 case 2
        $PARA=$context
    case 3
        $TITLE=$context
    case 4
        $TIMEOUT=$context
   EndSwitch
EndFunc
