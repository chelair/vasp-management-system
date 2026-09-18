#!/usr/bin/env bash
# 连接计算服务器（HPC）
#   目标：mdye@hpc.xmu.edu.cn（密钥 ~/.ssh/id_rsa）
#   用法：connect-hpc.sh                 # 交互登录
#         connect-hpc.sh --cmd '命令'    # 登录后执行一条命令并返回
#         connect-hpc.sh --pause         # 退出后等待按键（桌面快捷方式用，窗口不闪退）
#   前提：SecureLink 已连接（校园网路由需经 tun0，否则 22 端口不可达）
set -uo pipefail

HOST="${HPC_HOST:-hpc.xmu.edu.cn}"
USER_NAME="${HPC_USER:-mdye}"
KEY="$HOME/.ssh/id_rsa"
REMOTE_CMD=""
PAUSE=0

while [ $# -gt 0 ]; do
    case "$1" in
        --cmd) REMOTE_CMD="${2:-}"; shift 2 ;;
        --pause) PAUSE=1; shift ;;
        -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
        *) REMOTE_CMD="$*"; break ;;
    esac
done

# ---------- 检查 1：SSH 私钥 ----------
if [ ! -f "$KEY" ]; then
    echo "✗ 找不到私钥 $KEY" >&2
    echo "  （系统用 data/config/servers.json 的 key_path，默认 ~/.ssh/id_rsa）" >&2
    exit 2
fi
perm="$(stat -c '%a' "$KEY")"
if [ "$perm" != "600" ]; then
    echo "✗ 私钥权限是 $perm，应为 600：chmod 600 $KEY" >&2
    exit 2
fi

# ---------- 检查 2：SecureLink（校园 VPN）路由 ----------
ip="$(getent ahostsv4 "$HOST" 2>/dev/null | awk '{print $1}' | head -1)"
if [ -z "$ip" ]; then
    echo "✗ 无法解析 $HOST —— 检查网络 / DNS，或先连接 SecureLink。" >&2
    exit 3
fi
route="$(ip route get "$ip" 2>/dev/null | head -1)"
if ! printf '%s' "$route" | grep -q "dev tun0"; then
    echo "✗ 计算服务器必须经校园 VPN 访问，当前路由没有走 tun0：" >&2
    echo "    $route" >&2
    echo "  → 请先打开「SecureLink」客户端并连接，再重试。" >&2
    exit 4
fi
echo "· 路由正常：$route"

SSH_OPTS=(-o ServerAliveInterval=60 -o ServerAliveCountMax=4 -o StrictHostKeyChecking=accept-new)

# ---------- 连接 ----------
if [ -n "$REMOTE_CMD" ]; then
    ssh "${SSH_OPTS[@]}" "$USER_NAME@$HOST" "$REMOTE_CMD"
    status=$?
else
    echo "· 正在登录 $USER_NAME@$HOST（exit 或 Ctrl-D 退出）…"
    ssh "${SSH_OPTS[@]}" "$USER_NAME@$HOST"
    status=$?
fi

if [ "$PAUSE" = "1" ]; then
    echo
    read -r -n 1 -p "按任意键关闭窗口…" _ || true
    echo
fi
exit $status
