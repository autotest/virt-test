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
@fonts
@Smart Card Support
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
totem
%end

%post
echo "OS install is completed" > /dev/ttyS0
grubby --remove-args="rhgb quiet" --update-kernel=$(grubby --default-kernel)
dhclient
chkconfig sshd on
iptables -F
echo 0 > /selinux/enforce
chkconfig NetworkManager on
sed -i "/^HWADDR/d" /etc/sysconfig/network-scripts/ifcfg-eth0
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
cat >> '/etc/rc.modules' << EOF
modprobe snd-aloop
modprobe snd-pcm-oss
modprobe snd-mixer-oss
modprobe snd-seq-oss
EOF
chmod +x /etc/rc.modules
%end
