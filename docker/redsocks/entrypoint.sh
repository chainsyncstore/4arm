#!/bin/bash
set -e

# Default values (no proxy configured yet)
PROXY_HOST=${PROXY_HOST:-"0.0.0.0"}
PROXY_PORT=${PROXY_PORT:-"1080"}
PROXY_TYPE=${PROXY_TYPE:-"socks5"}
PROXY_USER=${PROXY_USER:-""}
PROXY_PASS=${PROXY_PASS:-""}

# Generate config from template
envsubst < /etc/redsocks.conf.tmpl > /etc/redsocks.conf

# Setup iptables to redirect all outbound TCP to redsocks
# Exclude local/private networks and DNS
iptables -t nat -N REDSOCKS 2>/dev/null || true
iptables -t nat -F REDSOCKS
iptables -t nat -A REDSOCKS -d 0.0.0.0/8 -j RETURN
iptables -t nat -A REDSOCKS -d 10.0.0.0/8 -j RETURN
iptables -t nat -A REDSOCKS -d 127.0.0.0/8 -j RETURN
iptables -t nat -A REDSOCKS -d 169.254.0.0/16 -j RETURN
iptables -t nat -A REDSOCKS -d 172.16.0.0/12 -j RETURN
iptables -t nat -A REDSOCKS -d 192.168.0.0/16 -j RETURN
iptables -t nat -A REDSOCKS -d 224.0.0.0/4 -j RETURN
iptables -t nat -A REDSOCKS -d 240.0.0.0/4 -j RETURN
# Exempt upstream proxy host so redsocks can reach it (avoid redirect loop)
if [ -n "${PROXY_HOST}" ] && [ "${PROXY_HOST}" != "0.0.0.0" ]; then
    PROXY_IP=$(getent hosts "${PROXY_HOST}" | awk '{print $1}' | head -n1)
    PROXY_IP=${PROXY_IP:-${PROXY_HOST}}
    iptables -t nat -A REDSOCKS -d "${PROXY_IP}" -j RETURN
fi
iptables -t nat -A REDSOCKS -p tcp -j REDIRECT --to-ports 12345

iptables -t nat -A OUTPUT -p tcp -j REDSOCKS
iptables -t nat -A PREROUTING -p tcp -j REDSOCKS

echo "Starting redsocks with proxy ${PROXY_HOST}:${PROXY_PORT} (${PROXY_TYPE})"
exec redsocks -c /etc/redsocks.conf
