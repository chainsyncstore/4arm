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

# Restart redsocks process
pkill -HUP redsocks 2>/dev/null || (pkill redsocks 2>/dev/null; sleep 1; redsocks -c /etc/redsocks.conf &)

echo "Proxy switched to ${PROXY_HOST}:${PROXY_PORT}"
