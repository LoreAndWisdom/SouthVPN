#!/usr/bin/env bash
# 04_configure_network.sh — Enable IP forwarding and configure UFW firewall.
# Idempotent: safe to run multiple times.
set -euo pipefail

# ── IPv4 forwarding ───────────────────────────────────────────────────────────
SYSCTL_FILE="/etc/sysctl.d/99-southvpn.conf"
if ! grep -q "net.ipv4.ip_forward=1" "$SYSCTL_FILE" 2>/dev/null; then
    echo "net.ipv4.ip_forward=1" > "$SYSCTL_FILE"
    sysctl -p "$SYSCTL_FILE"
    echo "IP forwarding enabled."
else
    echo "IP forwarding already configured."
fi

# ── Detect primary network interface ─────────────────────────────────────────
PRIMARY_IFACE=$(ip route show default | awk '/default/ {print $5}' | head -1)
if [[ -z "$PRIMARY_IFACE" ]]; then
    echo "ERROR: Cannot detect primary network interface from default route." >&2
    exit 1
fi
echo "Primary network interface: ${PRIMARY_IFACE}"

# ── UFW: allow VPN and SSH ────────────────────────────────────────────────────
ufw allow 1194/udp comment "SouthVPN OpenVPN"
ufw allow 22/tcp  comment "SSH"

# ── UFW masquerade (POSTROUTING NAT) ─────────────────────────────────────────
# UFW does not manage NAT rules via its CLI, so we edit before.rules directly.
UFW_BEFORE="/etc/ufw/before.rules"
if ! grep -q "SOUTHVPN MASQUERADE" "$UFW_BEFORE"; then
    echo "Adding masquerade NAT rules to ${UFW_BEFORE}..."
    MASQ_BLOCK="# BEGIN SOUTHVPN MASQUERADE\n*nat\n:POSTROUTING ACCEPT [0:0]\n-A POSTROUTING -s 10.8.0.0/8 -o ${PRIMARY_IFACE} -j MASQUERADE\nCOMMIT\n# END SOUTHVPN MASQUERADE\n"
    # Prepend before any *filter section
    sed -i "1s|^|${MASQ_BLOCK}|" "$UFW_BEFORE"
else
    echo "Masquerade rules already present."
fi

# ── UFW packet forwarding ─────────────────────────────────────────────────────
sed -i 's/^DEFAULT_FORWARD_POLICY=.*/DEFAULT_FORWARD_POLICY="ACCEPT"/' /etc/default/ufw

# ── Enable UFW ────────────────────────────────────────────────────────────────
ufw --force enable

echo "[OK] Network/firewall configured."
ufw status verbose
