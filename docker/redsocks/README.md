# 4ARM Redsocks Sidecar Image

Custom Docker image for transparent SOCKS5 proxying in 4ARM streaming farm instances.

## Architecture

Each Android instance runs as a POD of two containers:
- `redroid-N` — the Android container
- `redsocks-N` — transparent SOCKS5 sidecar with `network_mode: "container:redroid-N"`

All outbound TCP traffic from redroid is transparently redirected through the SOCKS5 proxy via iptables REDIRECT rules.

## Build Instructions

```bash
# Build the image
docker build -t 4arm-redsocks:latest .

# Tag for registry (optional)
docker tag 4arm-redsocks:latest your-registry.com/4arm-redsocks:latest

# Push to registry
docker push your-registry.com/4arm-redsocks:latest
```

## Configuration

The container is configured via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `PROXY_HOST` | `0.0.0.0` | SOCKS5 proxy host |
| `PROXY_PORT` | `1080` | SOCKS5 proxy port |
| `PROXY_TYPE` | `socks5` | Proxy type (socks5, socks4, http-connect, http-relay) |
| `PROXY_USER` | `""` | Proxy username (optional) |
| `PROXY_PASS` | `""` | Proxy password (optional) |

## Hot Reload

To switch proxies without restarting the container:

```bash
docker exec redsocks-01 /reload.sh <host> <port> <user> <pass> [type]
```

## iptables Rules

The entrypoint sets up the following rules:

1. Creates a `REDSOCKS` chain in the nat table
2. Excludes private networks (10.x, 172.16-31.x, 192.168.x, etc.)
3. Redirects all remaining TCP traffic to port 12345 (redsocks listener)
4. Applies chain to OUTPUT and PREROUTING

## Requirements

- `--cap-add NET_ADMIN` capability for iptables manipulation
- `network_mode: "container:<redroid-container>"` to share network namespace

## Testing

```bash
# Test proxy connectivity from within redroid container
docker exec redroid-01 curl -s https://api.ipify.org
```
