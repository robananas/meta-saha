#!/usr/bin/env bash
# Ubuntu 24.04 开机优化脚本
# 用法: sudo bash optimize-boot.sh

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 sudo 运行: sudo bash $0"
  exit 1
fi

echo "==> [1/4] 修复网络自动连接..."
nmcli connection modify "Wired connection 1" \
  connection.autoconnect no \
  ipv4.may-fail yes \
  ipv6.may-fail yes
echo "    Wired connection 1: autoconnect=off, may-fail=on"

echo "==> [2/4] 缩短 NetworkManager 网络等待超时 (60s -> 15s)..."
mkdir -p /etc/systemd/system/NetworkManager-wait-online.service.d
cat > /etc/systemd/system/NetworkManager-wait-online.service.d/override.conf << 'EOF'
[Service]
Environment=NM_ONLINE_TIMEOUT=15
EOF

echo "==> [3/4] 解除 Docker 对 network-online 的强依赖..."
mkdir -p /etc/systemd/system/docker.service.d
cat > /etc/systemd/system/docker.service.d/override.conf << 'EOF'
[Unit]
Wants=
Wants=containerd.service
After=
After=network.target nss-lookup.target docker.socket firewalld.service containerd.service time-set.target
EOF

echo "==> [4/4] 禁用不必要的开机服务..."
for svc in nfs-server nfs-blkmap apport ModemManager; do
  if systemctl is-enabled "$svc" &>/dev/null; then
    systemctl disable "$svc"
    echo "    已禁用: $svc"
  else
    echo "    跳过 (未启用): $svc"
  fi
done

systemctl daemon-reload

echo ""
echo "=========================================="
echo "  优化完成！请重启电脑使更改生效："
echo "  sudo reboot"
echo ""
echo "  重启后验证开机时间："
echo "  systemd-analyze"
echo "  systemd-analyze blame | head -10"
echo "=========================================="
