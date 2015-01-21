install
KVM_TEST_MEDIUM
graphical
poweroff
lang en_US.UTF-8
keyboard us
network --onboot yes --device eth0 --bootproto dhcp
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

%packages --ignoremissing
@base
@core
@development
@additional-devel
@debugging-tools
@network-tools
@fonts
@x11
@gnome-desktop
lftp
gcc
gcc-c++
patch
make
git
nc
NetworkManager
ntpdate
redhat-lsb
numactl-libs
numactl
sg3_utils
hdparm
lsscsi
libaio-devel
perl-Time-HiRes
flex
prelink
%end

%post
echo "OS install is completed" > /dev/ttyS0
echo "remove rhgb quiet by grubby" > /dev/ttyS0
grubby --remove-args="rhgb quiet" --update-kernel=$(grubby --default-kernel)
echo "dhclient" > /dev/ttyS0
dhclient
echo "get repo" > /dev/ttyS0
wget http://fileshare.englab.nay.redhat.com/pub/section2/repo/epel/rhel-autotest.repo -O /etc/yum.repos.d/rhel-autotest.repo
echo "yum makecache" > /dev/ttyS0
yum makecache
echo "yum install -y stress" > /dev/ttyS0
yum install -y stress
echo "chkconfig sshd on" > /dev/ttyS0
chkconfig sshd on
echo "PermitRootLogin in /etc/ssh/sshd_config" > /dev/ttyS0
sed -i 's/#PermitRootLogin yes/PermitRootLogin yes/g' /etc/ssh/sshd_config
echo "iptables -F" > /dev/ttyS0
iptables -F
echo "echo 0 > selinux/enforce" > /dev/ttyS0
echo 0 > /selinux/enforce
echo "chkconfig NetworkManager on" > /dev/ttyS0
chkconfig NetworkManager on
echo "update ifcfg-eth0" > /dev/ttyS0
sed -i "/^HWADDR/d" /etc/sysconfig/network-scripts/ifcfg-eth0
echo "Disable lock cdrom udev rules" > /dev/ttyS0
sed -i "/--lock-media/s/^/#/" /usr/lib/udev/rules.d/60-cdrom_id.rules 2>/dev/null>&1
echo 'Post set up finished' > /dev/ttyS0
echo Post set up finished > /dev/hvc0
%end
