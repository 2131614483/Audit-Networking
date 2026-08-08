#!/usr/bin/env python3
"""预制菜模块脚手架生成器 CLI。

子命令：
  list       列出所有可解析的方案文档（含 ID/家族/优先级/难度/平台/名称）
  generate   生成模块代码包（默认全部，不含 FA-01）
  validate   校验已生成模块（必选文件 + py_compile 语法）
  todos      扫描所有 # TODO[家族]: 待填扩展点

典型流程（在仓库根目录执行）：
  python tools/module-scaffold/scaffold.py list
  python tools/module-scaffold/scaffold.py generate --all
  python tools/module-scaffold/scaffold.py validate --all
  python tools/module-scaffold/scaffold.py todos

零第三方依赖，纯标准库。
"""
import argparse
import sys

import generate


def cmd_list(args) -> int:
    metas = generate.parse_all(generate.REPO_ROOT, include_fa01=True)
    if not metas:
        print("未找到可解析的方案文档（仓库根目录下应有 {PREFIX}-{NN}-名称.md）")
        return 1
    print(f"共解析 {len(metas)} 份方案文档：\n")
    print(f"{'ID':<8} {'家族':<12} {'优先':<7} {'难':<3} {'平台':<16} 名称")
    print("-" * 82)
    for m in metas:
        plats = ",".join(m.platforms)
        print(f"{m.id:<8} {m.family:<12} {m.priority:<7} {m.difficulty:<3} {plats:<16} {m.name}")
    fams = {}
    for m in metas:
        fams[m.family] = fams.get(m.family, 0) + 1
    print("\n家族分布：")
    for f, c in sorted(fams.items()):
        print(f"  {f:<14} {c} 个")
    return 0


def cmd_generate(args) -> int:
    if args.module:
        generate.generate_one(args.module, force=True)
    else:
        generate.generate_all(
            include_fa01=args.include_fa01,
            with_docker=args.with_docker,
            force=args.force,
        )
    return 0


def cmd_validate(args) -> int:
    if not args.all and not args.module:
        print("请指定 --all 或 --module FA-02")
        return 1
    target = None if args.all else args.module
    rc = generate.validate(target)
    return 1 if rc else 0


def cmd_todos(args) -> int:
    generate.list_todos(args.module)
    return 0


def main() -> None:
    p = argparse.ArgumentParser(
        prog="scaffold",
        description="审计预制菜模块脚手架生成器（代码规范化 + 省 token）",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="列出所有可解析的方案文档").set_defaults(func=cmd_list)

    g = sub.add_parser("generate", help="生成模块代码包")
    g.add_argument("--module", metavar="FA-02", help="只生成指定模块")
    g.add_argument("--all", action="store_true", help="生成全部（默认行为，不含 FA-01）")
    g.add_argument("--include-fa01", action="store_true", help="包含 FA-01")
    g.add_argument("--with-docker", action="store_true", help="额外生成顶层 docker-compose")
    g.add_argument("--force", action="store_true", help="覆盖已存在的模块文件")
    g.set_defaults(func=cmd_generate)

    v = sub.add_parser("validate", help="校验已生成模块")
    v.add_argument("--all", action="store_true", help="校验全部")
    v.add_argument("--module", metavar="FA-02", help="校验指定模块")
    v.set_defaults(func=cmd_validate)

    t = sub.add_parser("todos", help="扫描待填扩展点")
    t.add_argument("--module", metavar="FA-02", help="只看指定模块")
    t.set_defaults(func=cmd_todos)

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
