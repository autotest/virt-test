import CDROM
import fcntl
import os
import sys

if len(sys.argv) > 1:
    fd = os.open(sys.argv[1], os.O_RDONLY | os.O_NONBLOCK)

    if CDROM.CDS_TRAY_OPEN == fcntl.ioctl(fd, CDROM.CDROM_DRIVE_STATUS):
        print "cdrom is open"
    else:
        print "cdrom is close"

    os.close(fd)
