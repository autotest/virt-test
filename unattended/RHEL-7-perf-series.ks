install
KVM_TEST_MEDIUM
text
poweroff
lang en_US.UTF-8
keyboard us
network --bootproto dhcp
rootpw redhat
firewall --enabled --ssh
selinux --enforcing
timezone --utc America/New_York
firstboot --disable
bootloader --location=mbr --append="console=tty0 console=ttyS0,115200 elevator=deadline"
zerombr
clearpart --all --initlabel
autopart

%packages --ignoremissing
@base
@core
@development
@additional-devel
@debugging-tools
lftp
gcc
gcc-c++
patch
make
git
nc
ntpdate
redhat-lsb
gdb
rpcbind
nfs-utils
telnet
portmap
net-snmp
mkisofs
%end

%post
echo "OS install is completed" > /dev/ttyS0
grubby --remove-args="rhgb quiet" --update-kernel=$(grubby --default-kernel)
dhclient
wget http://fileshare.englab.nay.redhat.com/pub/section2/kvm/pub/autotest/repo/rhel-autotest.repo -O /etc/yum.repos.d/rhel-autotest.repo
yum makecache
yum install -y stress
chkconfig sshd on
iptables -F
echo 0 > /selinux/enforce
sed -i "/^HWADDR/d" /etc/sysconfig/network-scripts/ifcfg-eth0
echo "rm -rf /etc/udev/rules.d/70-persistent-net.rules " >> /etc/rc.local
echo 'Post set up finished' > /dev/ttyS0
echo Post set up finished > /dev/hvc0
%end
