install
KVM_TEST_MEDIUM
text
reboot
lang en_US.UTF-8
keyboard us
key --skip
network --bootproto dhcp
rootpw 123456
firewall --enabled --ssh
selinux --enforcing
timezone --utc America/New_York
firstboot --disable
bootloader --location=mbr --append="console=tty0 console=ttyS0,115200"
zerombr
clearpart --all --initlabel
autopart
reboot

%packages
@base
@development-libs
@development-tools
ntpdate

%post
echo "OS install is completed" > /dev/ttyS0
grubby --remove-args="rhgb quiet" --update-kernel=$(grubby --default-kernel)
dhclient
chkconfig sshd on
iptables -F
echo 0 > /selinux/enforce
sed -i "/^HWADDR/d" /etc/sysconfig/network-scripts/ifcfg-eth0
echo 'Post set up finished' > /dev/ttyS0
echo Post set up finished > /dev/hvc0
