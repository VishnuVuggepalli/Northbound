#!/bin/sh
# Northbound sandbox FRR entrypoint.
#
# The stock FRR image ships no SSH server, but Northbound's FreeBSD/FRR read
# path drives the device over SSH (`vtysh -c "show running-config"`). So we:
#   1. install + configure openssh,
#   2. create the `nbadmin` login the sandbox creds use,
#   3. start frr daemons,
#   4. hand off to sshd in the foreground.
#
# Everything here is sandbox-only convenience. Production FRR/FreeBSD already
# has sshd; Northbound never installs anything on a managed device.
set -e

NB_USER="${NB_USER:-nbadmin}"
NB_PASS="${NB_PASS:-nbsandbox}"

# FRR base image is Alpine-based in recent tags; fall back to apk/apt.
if command -v apk >/dev/null 2>&1; then
    apk add --no-cache openssh openssh-server >/dev/null 2>&1 || true
    PKG=apk
elif command -v apt-get >/dev/null 2>&1; then
    apt-get update >/dev/null 2>&1 && apt-get install -y --no-install-recommends openssh-server >/dev/null 2>&1 || true
    PKG=apt
fi

# Host keys.
ssh-keygen -A >/dev/null 2>&1 || true

# Login user that can run vtysh. Add to frrvty/frr groups so `vtysh` works.
if ! id "$NB_USER" >/dev/null 2>&1; then
    if [ "$PKG" = "apk" ]; then
        adduser -D -s /bin/sh "$NB_USER" || true
    else
        useradd -m -s /bin/sh "$NB_USER" || true
    fi
fi
echo "${NB_USER}:${NB_PASS}" | chpasswd 2>/dev/null || true
addgroup "$NB_USER" frrvty 2>/dev/null || usermod -aG frrvty "$NB_USER" 2>/dev/null || true
addgroup "$NB_USER" frr    2>/dev/null || usermod -aG frr    "$NB_USER" 2>/dev/null || true

# Permit password auth for the sandbox login.
SSHD_CFG=/etc/ssh/sshd_config
{
    echo "PasswordAuthentication yes"
    echo "PermitRootLogin yes"
    echo "UsePAM no"
} >> "$SSHD_CFG" 2>/dev/null || true

# Start FRR daemons (best effort; the watchfrr/init differs across tags).
/usr/lib/frr/frrinit.sh start >/dev/null 2>&1 \
    || /etc/init.d/frr start >/dev/null 2>&1 \
    || (/usr/lib/frr/zebra -d -A 127.0.0.1 >/dev/null 2>&1; /usr/lib/frr/bgpd -d -A 127.0.0.1 >/dev/null 2>&1) \
    || true

# sshd in the foreground keeps the container alive.
exec /usr/sbin/sshd -D -e
