#!/usr/bin/env bash
# 02_setup_pki.sh — Initialize CA and server certificate via easy-rsa (ECDH).
# Uses prime256v1 curve — no slow DH parameter generation required.
set -euo pipefail

EASYRSA_DIR="/etc/openvpn/easy-rsa"
SERVER_DIR="/etc/openvpn/server"

mkdir -p "$SERVER_DIR"

if [[ ! -d "$EASYRSA_DIR" ]]; then
    echo "Copying easy-rsa to ${EASYRSA_DIR}..."
    cp -r /usr/share/easy-rsa "$EASYRSA_DIR"
fi

cd "$EASYRSA_DIR"

# ── PKI init ─────────────────────────────────────────────────────────────────
if [[ ! -d "pki" ]]; then
    echo "Initializing PKI..."
    ./easyrsa init-pki
fi

# ── Certificate Authority ─────────────────────────────────────────────────────
if [[ ! -f "pki/ca.crt" ]]; then
    echo "Building CA (ECDH prime256v1)..."
    EASYRSA_ALGO=ec EASYRSA_CURVE=prime256v1 \
        ./easyrsa --batch build-ca nopass
fi

# ── Server certificate ────────────────────────────────────────────────────────
if [[ ! -f "pki/issued/server.crt" ]]; then
    echo "Generating server certificate..."
    EASYRSA_ALGO=ec EASYRSA_CURVE=prime256v1 \
        ./easyrsa --batch gen-req server nopass
    EASYRSA_ALGO=ec EASYRSA_CURVE=prime256v1 \
        ./easyrsa --batch sign-req server server
fi

# ── TLS auth key ──────────────────────────────────────────────────────────────
if [[ ! -f "$SERVER_DIR/ta.key" ]]; then
    echo "Generating TLS auth key..."
    openvpn --genkey secret "$SERVER_DIR/ta.key"
fi

# ── Copy artifacts to server directory ───────────────────────────────────────
cp pki/ca.crt         "$SERVER_DIR/ca.crt"
cp pki/issued/server.crt "$SERVER_DIR/server.crt"
cp pki/private/server.key "$SERVER_DIR/server.key"
chmod 600 "$SERVER_DIR/server.key"

echo "[OK] PKI initialized. Files in ${SERVER_DIR}:"
ls -l "$SERVER_DIR"
