import os
import sys
import datetime


def set_time(nsec):
    now = datetime.datetime.now()
    time = now + datetime.timedelta(seconds=float(nsec))
    if "nt" in sys.platform:
        cmd = "date '%s' & " % time.strftime("%x")
        cmd += "time '%s'" % time.strftime("%X")
    else:
        cmd = "date -s '%s'" % time.strftime("%c")
    os.system(cmd)


def show_time():
    now = datetime.datetime.now()
    print now.ctime()

if __name__ == "__main__":
    try:
        nsec = float(sys.argv[1])
    except IndexError:
        show_time()
        sys.exit(0)
    set_time(nsec)
