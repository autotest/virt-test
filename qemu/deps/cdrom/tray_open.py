import os
import sys

if len(sys.argv) > 1:
    if "linux" in sys.platform:
        import CDROM
        import fcntl
        fd = os.open(sys.argv[1], os.O_RDONLY | os.O_NONBLOCK)

        if CDROM.CDS_TRAY_OPEN == fcntl.ioctl(fd, CDROM.CDROM_DRIVE_STATUS):
            print "cdrom is open"
        else:
            print "cdrom is close"

        os.close(fd)
    else:
        import ctypes
        msg = u"open %s: type cdaudio alias d_drive" % sys.argv[1]
        ctypes.windll.WINMM.mciSendStringW(msg, None, 0, None)
        msg = u"status d_drive length"
        if ctypes.windll.WINMM.mciSendStringW(msg, None, 0, None) == 0:
            print "cdrom is close"
        else:
            print "cdrom is open"
