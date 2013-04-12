#!/usr/bin/env python

import sys
import commands
import time
import shutil

arp_values = {'arp_ignore':2, 'arp_announce':2}
arp_items = ['"net.ipv4.conf.default.arp_ignore = 2"',
            '"net.ipv4.conf.default.arp_announce = 2"']
sys_ctrl = '/etc/sysctl.conf'
sys_ctrl_bak = "".join([sys_ctrl, ".bak"])

print "backing up the original config file..."
shutil.copy(sys_ctrl, sys_ctrl_bak)

print "preparing the config file..."
for arp_i in arp_items:
    (s, o) = commands.getstatusoutput(" ".join(["grep", arp_i, sys_ctrl]))
    if s != 0:
        print "No previous settings for %s, lets do it..." % arp_i
        (s, o) = commands.getstatusoutput("echo '%s' >> %s" %(arp_i, sys_ctrl))
        if s != 0:
            print "Add arp config info failed with output: %s" % o
            sys.exit(-1)
    print "%s exists in %s" % (arp_i, sys_ctrl)

# make the configurations take effect
print "Fire the setting changes..."
(s, o) = commands.getstatusoutput("sysctl -p")
if s != 0:
    print "Execute 'sysctl -p' failed with %s" % o
    sys.exit(-1)

#
print "lets have a rest..."
time.sleep(10)

# verify the configurations
for key in arp_values.keys():
    query_cmd = "cat /proc/sys/net/ipv4/conf/default/%s" % key
    (s, o) = commands.getstatusoutput(query_cmd)
    if s != 0:
        print "Query %s failed with output %s" % (key, o)
        sys.exit(-1)
    if int(o) != arp_values.get(key):
        print "ARP settings failed, the conf file has not taken effects."
        sys.exit(-1)
    print "%s settings are good." % key

# restart networking
print "So far so good, lets restart networking..."
(s, o) = commands.getstatusoutput("/etc/init.d/network restart")
if s != 0:
    print "Doomed. Network restarting failed. PANIC! Anybody help!"
    sys.exit(-1)

print "We are doing good! PASSED."

