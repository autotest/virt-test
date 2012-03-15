install
KVM_TEST_MEDIUM
text
reboot
lang en_US.UTF-8
keyboard us
key --skip
network --bootproto dhcp
rootpw redhat
firewall --enabled --ssh
selinux --enforcing
timezone --utc America/New_York
firstboot --disable
bootloader --location=mbr --append="console=tty0 console=ttyS0,115200"
zerombr
clearpart --all --initlabel
autopart
xconfig --startxonboot

%packages
@base
@development-libs
@development-tools
@gnome-desktop
@base-x
@core
xorg-x11-utils
xorg-x11-server-Xnest
kexec-tools
gcc
patch
make
nc
ntp
redhat-lsb

%post --interpreter /usr/bin/python
import os
os.system('echo "OS install is completed" > /dev/ttyS0')
os.system('dhclient')
os.system('chkconfig sshd on')
os.system('iptables -F')
os.system('echo 0 > /selinux/enforce')
os.system('sed -i "/^HWADDR/d" /etc/sysconfig/network-scripts/ifcfg-eth0')
os.system("echo 'Post set up finished' > /dev/ttyS0")
os.system('echo Post set up finished > /dev/hvc0')
