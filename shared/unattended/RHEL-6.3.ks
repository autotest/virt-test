install
KVM_TEST_MEDIUM
text
reboot
lang en_US.UTF-8
keyboard us
key --skip
network --bootproto dhcp
rootpw --plaintext 123456
user --name=test --password=123456 --plaintext
firewall --enabled --ssh
selinux --enforcing
timezone --utc America/New_York
firstboot --disable
bootloader --location=mbr --append="console=tty0 console=ttyS0,115200"
zerombr
xconfig --startxonboot
clearpart --all --initlabel
autopart
poweroff
KVM_TEST_LOGGING

%packages
@base
@core
@development
@additional-devel
@debugging-tools
@network-tools
@x11
@basic-desktop
NetworkManager
ntpdate
watchdog
coreutils
usbutils
spice-xpi
virt-viewer
spice-vdagent
usbredir
SDL
%end

%post --nochroot --interpreter /usr/bin/python
import os
os.system('grubby --remove-args="rhgb quiet" --update-kernel=$(grubby --default-kernel)')
os.system('dhclient')
os.system('chkconfig sshd on')
os.system('iptables -F')
os.system('echo 0 > /selinux/enforce')
os.system('echo Post set up finished > /dev/ttyS0')
os.system('echo Post set up finished > /dev/hvc0')
f = open('/mnt/sysimage/etc/gdm/custom.conf','w')
f.write('[daemon]\n'
        'AutomaticLogin=test\n'
        'AutomaticLoginEnable=True\n')
%end
