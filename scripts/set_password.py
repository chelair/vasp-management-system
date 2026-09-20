"""账号管理 CLI（账号体系第 1 步）：建号 / 改密 / 禁用 / 启用 / 列出用户。

用法（在生产机仓库根目录执行）：

    python scripts/set_password.py                                  # 列出所有用户
    python scripts/set_password.py mdye                             # 建号或改密（交互输入，两次确认）
    python scripts/set_password.py mdye --generate                  # 生成随机密码并打印
    python scripts/set_password.py mdye --password 'xxx'            # 直接指定（注意 shell 历史）
    python scripts/set_password.py mdye --role admin                # 建号时指定角色（admin/user/agent）
    python scripts/set_password.py mdye --disable                   # 禁用（同时吊销其全部会话）
    python scripts/set_password.py mdye --enable                    # 启用
    python scripts/set_password.py mdye --sessions                  # 列出该用户的有效会话
    python scripts/set_password.py mdye --revoke-sessions           # 强制下线（吊销全部会话）
    python scripts/set_password.py --data-dir <数据根目录>           # 指定数据目录（测试隔离）

说明：

- 不带参数时若 `data/users/users.json` 不存在，会**先自动创建默认管理员**
  （`zouyuxi`，随机密码打印一次），与后端首次启动行为一致。
- 密码策略：至少 8 位；系统只存 scrypt 哈希，明文只在生成时打印一次。
- 所有读写都走 `backend/auth.py` 的加锁实现，可安全地与运行中的服务并发执行。
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"

parser = argparse.ArgumentParser(description="账号管理（建号/改密/禁用/启用/列表）")
parser.add_argument("username", nargs="?", help="用户名（省略则列出所有用户）")
parser.add_argument("--password", help="直接指定密码（省略则交互输入或配合 --generate）")
parser.add_argument("--generate", action="store_true", help="生成随机密码并打印")
parser.add_argument("--role", choices=("admin", "user", "agent"), help="建号时的角色（默认 user）")
parser.add_argument("--disable", action="store_true", help="禁用该用户")
parser.add_argument("--enable", action="store_true", help="启用该用户")
parser.add_argument("--sessions", action="store_true", help="列出该用户的有效会话")
parser.add_argument("--revoke-sessions", action="store_true", help="吊销该用户全部会话（强制下线）")
parser.add_argument(
    "--data-dir",
    help="数据根目录（默认项目下 data/；等价于后端 --data-dir，用于测试隔离）",
)
args = parser.parse_args()

if args.data_dir:
    os.environ["VASP_WEB_DATA_DIR"] = os.path.abspath(args.data_dir)

sys.path.insert(0, str(BACKEND))

import auth  # noqa: E402


def _print_users() -> None:
    users = auth.list_users()
    if not users:
        print("（还没有用户）")
        return
    print(f"共 {len(users)} 个用户（文件：{auth.USERS_FILE}）\n")
    header = f"{'用户名':<16}{'角色':<8}{'状态':<8}{'创建时间':<22}会话"
    print(header)
    print("-" * 66)
    for user in users:
        sessions = len(auth.list_sessions(user_id=user.get("user_id")))
        print(
            f"{str(user.get('username')):<16}"
            f"{str(user.get('role')):<8}"
            f"{'启用' if user.get('enabled') else '禁用':<8}"
            f"{str(user.get('created_at')):<22}"
            f"{sessions}"
        )


def _prompt_password() -> str:
    first = getpass.getpass("新密码（至少 8 位）：")
    second = getpass.getpass("再输入一次：")
    if first != second:
        print("两次输入不一致，已取消")
        sys.exit(1)
    return first


def _resolve_password() -> Optional[str]:
    """决定本次要设置的密码：`--password` > `--generate` > 交互输入 > 非交互时自动生成。

    返回 None 表示"交给 auth 生成随机密码"。
    """
    if args.password:
        return args.password
    if args.generate:
        return None
    if sys.stdin.isatty():
        return _prompt_password()
    print("提示：当前不是交互终端，改为生成随机密码（也可用 --password / --generate 明确指定）")
    return None


def main() -> int:
    # 与后端首次启动一致：没有 users.json 就先建默认管理员
    created = auth.ensure_users_file(print_password=False)
    if created["created"]:
        print(f"\n（已自动创建默认管理员 {created['username']}，初始密码：{created['password']}）\n")

    username = args.username
    if not username:
        _print_users()
        return 0

    user = auth.find_user(username)

    # 启用/禁用
    if args.disable or args.enable:
        if not user:
            print(f"用户不存在：{auth.normalize_username(username)}")
            return 1
        updated = auth.set_enabled(username, bool(args.enable))
        print(
            f"用户 {updated['username']} 已{'启用' if updated['enabled'] else '禁用'}"
            + ("" if updated["enabled"] else "（其全部会话已吊销）")
        )
        return 0

    # 会话管理
    if args.sessions or args.revoke_sessions:
        if not user:
            print(f"用户不存在：{auth.normalize_username(username)}")
            return 1
        if args.revoke_sessions:
            count = auth.revoke_user_sessions(user["user_id"])
            print(f"已吊销 {user['username']} 的 {count} 个会话")
            return 0
        sessions = auth.list_sessions(user_id=user["user_id"])
        if not sessions:
            print(f"{user['username']} 当前没有有效会话")
            return 0
        print(f"{user['username']} 的有效会话 {len(sessions)} 个：")
        for s in sessions:
            print(
                f"  - {s.get('name') or '(未命名)':<16} 创建 {s.get('created_at')}"
                f" · 最近使用 {s.get('last_seen')} · 过期 {s.get('expires_at')}"
            )
        return 0

    # 建号 / 改密
    if not user:
        role = args.role or "user"
        try:
            record, plain = auth.create_user(username, password=_resolve_password(), role=role)
        except auth.AuthError as e:
            print(f"建号失败：{e}")
            return 1
        print(f"已创建用户 {record['username']}（角色 {record['role']}）")
    else:
        if args.role and args.role != user.get("role"):
            print("提示：已有用户的角色不会用本命令修改（避免误提权），需要时请直接改 users.json 或另开脚本")
        try:
            record, plain = auth.set_password(username, password=_resolve_password())
        except auth.AuthError as e:
            print(f"改密失败：{e}")
            return 1
        print(f"已更新用户 {record['username']} 的密码（旧会话已全部吊销）")

    if plain:
        print(f"  随机密码：{plain}")
        print("  请立即记录并修改：python scripts/set_password.py " + record["username"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
