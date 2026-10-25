"""Single-process server with an explicit proxy trust boundary."""
import os
from ipaddress import ip_network
import uvicorn

# Published at https://www.cloudflare.com/ips-v4 and /ips-v6 (26 October 2026).
# Render's public ingress traverses Cloudflare, then its private 10/8 proxies.
# Walk X-Forwarded-For from the right; never trust arbitrary client prefixes.
CLOUDFLARE_NETWORKS = (
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22", "2400:cb00::/32",
    "2606:4700::/32", "2803:f800::/32", "2405:b500::/32", "2405:8100::/32",
    "2a06:98c0::/29", "2c0f:f248::/32",
)


def trusted_proxy_ips():
    configured = os.getenv("TRUSTED_PROXY_CIDRS")
    if configured is None:
        networks = ["127.0.0.1", "::1"]
        if os.getenv("RENDER", "").lower() == "true":
            networks += ["10.0.0.0/8", *CLOUDFLARE_NETWORKS]
    else:
        networks = [value.strip() for value in configured.split(",") if value.strip()]
    for value in networks:
        network = ip_network(value)
        if network.prefixlen == 0:
            raise ValueError("Trust specific proxy networks, not every client address")
    return ",".join(networks)


if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")),
                workers=1, proxy_headers=True, forwarded_allow_ips=trusted_proxy_ips())
