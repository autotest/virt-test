set serialpath=%1serialport.exe
set serialcfgpath=%1serialport.cfg

if [%1]==[] set serialpath=%~dp0serialport.exe 

if [%1]==[] set serialcfgpath=%~dp0serialport.cfg

copy %serialpath% C:\serialport.exe



copy %serialcfgpath% C:\serialport.cfg

reg add "HKLM\Software\Microsoft\Windows\CurrentVersion\Run" /v "Serial Port Server" /d "C:\serialport.exe" /t REG_SZ /f


rem Just in case reg.exe is missing (e.g. Windows 2000):

regedit /s %~dp0\serialport.reg
