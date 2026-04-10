#!/usr/bin/env bash
# 01_install_packages.sh — Install all apt packages required by SouthVPN.
set -euo pipefail

PACKAGES=(
    openvpn
    easy-rsa
    libpam-google-authenticator
    pamtester
    ufw
    python3
    python3-pip
    python3-googleapi
    python3-google-auth
    python3-google-auth-httplib2
    qrencode
)

export DEBIAN_FRONTEND=noninteractive
export UCF_FORCE_CONFFOLD=1

echo "Updating package index..."
apt-get update -qq

echo "Installing packages: ${PACKAGES[*]}"
apt-get install -y --no-install-recommends "${PACKAGES[@]}"

echo "[OK] Packages installed."
