install
KVM_TEST_MEDIUM
text
reboot
lang en_US.UTF-8
keyboard us
network --onboot yes --device eth0 --bootproto dhcp --noipv6 --hostname atest-guest
rootpw 123456
firewall --disabled
selinux --disabled
timezone --utc America/New_York
firstboot --disable
bootloader --location=mbr --timeout=0 --append="console=tty0 console=ttyS0,115200"
zerombr
poweroff
services --enabled network
KVM_TEST_LOGGING

clearpart --all --initlabel
part / --fstype=ext4 --grow --asprimary --size=1

%packages
gpgme
hardlink
dmidecode
ethtool
tcpdump
tar
bzip2
pciutils
usbutils
-yum-utils
-cryptsetup
-vconfig
-dump
-acpid
-mlocate
-stunnel
-rng-tools
-ntfs-3g
-sos
-jwhois
-fedora-release-notes
-pam_pkcs11
-wireless-tools
-rdist
-mdadm
-dmraid
-ftp
-rsync
-system-config-network-tui
-pam_krb5
-nano
-nc
-PackageKit-yum-plugin
-btrfs-progs
-ypbind
-yum-presto
-microcode_ctl
-finger
-krb5-workstation
-ntfsprogs
-iptstate
-fprintd-pam
-irqbalance
-dosfstools
-mcelog
-smartmontools
-lftp
-unzip
-rsh
-telnet
-setuptool
-bash-completion
-pinfo
-rdate
-system-config-firewall-tui
-nfs-utils
-words
-cifs-utils
-prelink
-wget
-dos2unix
-passwdqc
-coolkey
-symlinks
-pm-utils
-bridge-utils
-zip
-eject
-numactl
-mtr
-sssd
-pcmciautils
-tree
-hunspell
-irda-utils
-time
-man-pages
-yum-langpacks
-talk
-wpa_supplicant
-kbd-misc
-kbd
-slang
-authconfig
-newt
-newt-python
-ntsysv
-libnl3
-tcp_wrappers
-quota
-libpipeline
-man-db
-groff
-less
-plymouth-core-libs
-plymouth
-plymouth-scripts
-libgudev1
-ModemManager
-NetworkManager-glib
-selinux-policy
-selinux-policy-targeted
-crontabs
-cronie
-cronie-anacron
-cyrus-sasl
-sendmail
-netxen-firmware
-linux-firmware
-libdaemon
-avahi-autoipd
-libpcap
-ppp
-libsss_sudo
-sudo
-at
-psacct
-parted
-passwd
-bind-utils
-tmpwatch
-bc
-acl
-attr
-traceroute
-mailcap
-quota-nls
-mobile-broadband-provider-info
-audit
-e2fsprogs-libs
-e2fsprogs
-biosdevname
-dbus-glib
-libdrm
-setserial
-lsof
-ed
-cyrus-sasl-plain
-dnsmasq
-system-config-firewall-base
-hesiod
-libpciaccess
-diffutils
-policycoreutils
-m4
-checkpolicy
-procmail
-libuser
-polkit
%end

%post --interpreter /usr/bin/python
import os
os.system('grubby --remove-args="rhgb quiet" --update-kernel=$(grubby --default-kernel)')
os.system('dhclient')
os.system('chkconfig sshd on')
os.system('iptables -F')
os.system('echo 0 > /selinux/enforce')
os.system('echo Post set up finished > /dev/ttyS0')
os.system('echo Post set up finished > /dev/hvc0')
%end
