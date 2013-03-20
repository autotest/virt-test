
If $CmdLine[0] = 1 Then
	$ip = $CmdLine[1]
	;MsgBox(0, "Get ip", $ip, 5)
Else
	$ip = "127.0.0.1"
EndIf

;==============================================
;==============================================
;CLIENT! Start Me after starting the SERVER!!!!!!!!!!!!!!!
;==============================================
;==============================================

; Start The TCP Services
;==============================================
TCPStartup()

; Initialize a variable to represent a connection
;==============================================
$ConnectedSocket = -1

;Attempt to connect to SERVER at its IP and PORT 33891
;=======================================================
$ConnectedSocket = TCPConnect($ip, 12323)

TCPSend($ConnectedSocket, "done")

TCPCloseSocket($ConnectedSocket)