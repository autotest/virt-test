install
KVM_TEST_MEDIUM
text
poweroff
lang en_US.UTF-8
langsupport --default=en_US.UTF-8 en_US.UTF-9
keyboard us
network --bootproto dhcp
rootpw 123456
firewall --enabled --ssh
timezone America/New_York
firstboot --disable
bootloader --location=mbr --append="console=tty0 console=ttyS0,115200"
clearpart --all --initlabel
autopart
mouse generic3ps/2
skipx

%packages --resolvedeps
@ base
@ development-libs
@ development-tools
gcc
patch
make
nc
ntp
redhat-lsb

%post
echo "OS install is completed" > /dev/ttyS0
cd home
echo "s0:2345:respawn:/sbin/agetty -L -f /etc/issue 115200 ttyS0 vt100" >> /etc/inittab
echo "ttyS0" >> /etc/securetty
cat > post_script.py << ABC
import  os
os.system('dhclient')
os.system('chkconfig sshd on')
os.system('sed -i "/^HWADDR/d" /etc/sysconfig/network-scripts/ifcfg-eth0')
os.system("echo 'Post set up finished' > /dev/ttyS0")
os.system('echo Post set up finished > /dev/hvc0')
ABC
python post_script.py
%end
