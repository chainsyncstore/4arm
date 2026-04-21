#!/bin/bash
# Usage: reload.sh <host> <port> <user> <pass> [type]
# Swaps proxy config without container restart

PROXY_HOST="${1}"
PROXY_PORT="${2}"
PROXY_USER="${3:-""}"
PROXY_PASS="${4:-""}"
PROXY_TYPE="${5:-socks5}"

export PROXY_HOST PROXY_PORT PROXY_USER PROXY_PASS PROXY_TYPE
envsubst < /etc/redsocks.conf.tmpl > /etc/redsocks.conf

# Rebuild REDSOCKS chain so only the current upstream proxy is exempt
iptables -t nat -F REDSOCKS 2>/dev/null || true
iptables -t nat -A REDSOCKS -d 0.0.0.0/8 -j RETURN
iptables -t nat -A REDSOCKS -d 10.0.0.0/8 -j RETURN
iptables -t nat -A REDSOCKS -d 127.0.0.0/8 -j RETURN
iptables -t nat -A REDSOCKS -d 169.254.0.0/16 -j RETURN
iptables -t nat -A REDSOCKS -d 172.16.0.0/12 -j RETURN
iptables -t nat -A REDSOCKS -d 192.168.0.0/16 -j RETURN
iptables -t nat -A REDSOCKS -d 224.0.0.0/4 -j RETURN
iptables -t nat -A REDSOCKS -d 240.0.0.0/4 -j RETURN
if [ -n "${PROXY_HOST}" ] && [ "${PROXY_HOST}" != "0.0.0.0" ]; then
    PROXY_IP=$(getent hosts "${PROXY_HOST}" | awk '{print $1}' | head -n1)
    PROXY_IP=${PROXY_IP:-${PROXY_HOST}}
    iptables -t nat -A REDSOCKS -d "${PROXY_IP}" -j RETURN
fi
iptables -t nat -A REDSOCKS -p tcp -j REDIRECT --to-ports 12345

# Restart redsocks process so it picks up new config
pkill redsocks 2>/dev/null || true
sleep 1
redsocks -c /etc/redsocks.conf &

echo "Proxy switched to ${PROXY_HOST}:${PROXY_PORT}"
