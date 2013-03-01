install
KVM_TEST_MEDIUM
text
poweroff
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
#partitioning
clearpart --all --initlabel
part /boot --fstype=ext4 --size=500
part pv.01  --grow --size=1
volgroup VolGroup --pesize=131072  pv.01
logvol swap --name=LogVol_swap --vgname=VolGroup --size=4096
logvol / --fstype=ext4 --name=LogVol_root --vgname=VolGroup --size=1 --grow
xconfig --startxonboot

%packages --ignoremissing
@base
@core
@development
@additional-devel
@debugging-tools
@network-tools
@basic-desktop
@desktop-platform
@fonts
@general-desktop
@graphical-admin-tools
@x11
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
qemu-guest-agent

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
chkconfig NetworkManager on
sed -i "/^HWADDR/d" /etc/sysconfig/network-scripts/ifcfg-eth0
echo 'Post set up finished' > /dev/ttyS0
echo Post set up finished > /dev/hvc0
%end
