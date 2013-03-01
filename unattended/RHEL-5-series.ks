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
part /boot --fstype=ext3 --size=500
part pv.01  --grow --size=1
volgroup VolGroup --pesize=131072  pv.01
logvol swap --name=LogVol_swap --vgname=VolGroup --size=4096
logvol / --fstype=ext4 --name=LogVol_root --vgname=VolGroup --size=1 --grow
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

%post
echo "OS install is completed" > /dev/ttyS0
grubby --remove-args="rhgb quiet" --update-kernel=$(grubby --default-kernel)
grubby --args="divider=10 crashkernel=128M@16M" --update-kernel=$(grubby --default-kernel)
dhclient
wget http://fileshare.englab.nay.redhat.com/pub/section2/kvm/pub/autotest/repo/rhel-autotest.repo -O /etc/yum.repos.d/rhel-autotest.repo
yum install -y stress
chkconfig sshd on
iptables -F
echo 0 > /selinux/enforce
sed -i "/^HWADDR/d" /etc/sysconfig/network-scripts/ifcfg-eth0
echo 'Post set up finished' > /dev/ttyS0
echo Post set up finished > /dev/hvc0
%end
