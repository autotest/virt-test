install
KVM_TEST_MEDIUM
text
lang en_US.UTF-8
keyboard us
network --onboot yes --device eth0 --bootproto dhcp --noipv6
rootpw 123456
firewall --enabled --ssh
selinux --enforcing
timezone --utc America/New_York
firstboot --disable
zerombr
bootloader --location=mbr --append="crashkernel=auto console=hvc0 rhgb quiet"
autopart --type=lvm
clearpart --all --initlabel
poweroff
KVM_TEST_LOGGING

%packages --ignoremissing
@base
@core
@development
@additional-devel
@debugging-tools
gcc
gcc-c++
make
git
%end

%post
echo "OS install is completed" > /dev/hvc0
dhclient
chkconfig sshd on
iptables -F
sed -i "/^HWADDR/d" /etc/sysconfig/network-scripts/ifcfg-eth0
echo "Post set up finished" > /dev/hvc0
%end
