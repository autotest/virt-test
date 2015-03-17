install
KVM_TEST_MEDIUM
poweroff
lang en_US.UTF-8
keyboard us
network --bootproto dhcp 
rootpw --plaintext 123456
firstboot --disable
user --name=test --password=123456
firewall --enabled --ssh
selinux --enforcing
timezone --utc America/New_York
bootloader --location=mbr --append="console=tty0 console=ttyS0,115200"
zerombr
KVM_TEST_LOGGING
clearpart --all --initlabel
autopart
xconfig --startxonboot

%packages --ignoremissing
@base
@core
@development
@additional-devel
@debugging
@network-tools
@x11
@gnome-desktop
@fonts
@smart-card
gnome-utils
python-imaging
NetworkManager
ntpdate
dconf
watchdog
coreutils
usbutils
spice-xpi
spice-gtk3
docbook-utils
sgml-common
openjade
virt-viewer
pulseaudio-libs-devel
mesa-libGL-devel
pygtk2-devel
libjpeg-turbo-devel
spice-vdagent
usbredir
SDL
totem
dmidecode
alsa-utils
-gnome-initial-setup
%end

%post
function ECHO { for TTY in `cat /proc/consoles | cut -f1 -d' '`; do echo "$*" > /dev/$TTY; done }
ECHO "OS install is completed"
ECHO "remove rhgb quiet by grubby"
grubby --remove-args="rhgb quiet" --update-kernel=$(grubby --default-kernel)
ECHO "dhclient"
dhclient
ECHO "get repo"
wget http://fileshare.englab.nay.redhat.com/pub/section2/repo/epel/rhel-autotest.repo -O /etc/yum.repos.d/rhel-autotest.repo
ECHO "yum makecache"
yum makecache
ECHO "yum install -y stress"
yum install -y stress
ECHO "chkconfig sshd on"
chkconfig sshd on
ECHO "iptables -F"
iptables -F
ECHO "echo 0 > selinux/enforce"
echo 0 > /selinux/enforce
ECHO "chkconfig NetworkManager on"
chkconfig NetworkManager on
ECHO "update ifcfg-eth0"
sed -i "/^HWADDR/d" /etc/sysconfig/network-scripts/ifcfg-eth0
ECHO "Disable lock cdrom udev rules"
sed -i "/--lock-media/s/^/#/" /usr/lib/udev/rules.d/60-cdrom_id.rules 2>/dev/null>&1
#Workaround for graphical boot as anaconda seems to always instert skipx
systemctl set-default graphical.target
sed -i "/^HWADDR/d" /etc/sysconfig/network-scripts/ifcfg-ens*
sed -i "s/ONBOOT=no/ONBOOT=yes/" /etc/sysconfig/network-scripts/ifcfg-ens*
echo 'Post set up finished' > /dev/ttyS0
echo Post set up finished > /dev/hvc0
cat > '/etc/gdm/custom.conf' << EOF
[daemon]
AutomaticLogin=test
AutomaticLoginEnable=True
EOF
cat >> '/etc/sudoers' << EOF
test ALL = NOPASSWD: /sbin/shutdown -r now,/sbin/shutdown -h now
EOF
cat >> '/home/test/.bashrc' << EOF
alias shutdown='sudo shutdown'
EOF
%end
