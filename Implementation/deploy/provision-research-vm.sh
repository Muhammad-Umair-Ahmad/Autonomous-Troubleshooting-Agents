#!/bin/sh
# Run only INSIDE the project-specific disposable Ubuntu 24.04 VM.
set -eu
export DEBIAN_FRONTEND=noninteractive
. /etc/os-release
[ "$ID" = ubuntu ] && [ "$VERSION_ID" = 24.04 ]
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl git python3.12-venv "linux-modules-extra-$(uname -r)"
modprobe vrf
ip link add neta-vrf type vrf table 1234
ip -d link show neta-vrf
ip link delete neta-vrf
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<'EOF'
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: arm64
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update
apt-get install -y --no-install-recommends docker-ce=5:28.5.2-1~ubuntu.24.04~noble docker-ce-cli=5:28.5.2-1~ubuntu.24.04~noble containerd.io docker-buildx-plugin
apt-mark hold docker-ce docker-ce-cli
systemctl enable --now docker
docker version
python3 --version
free -m
df -h /
