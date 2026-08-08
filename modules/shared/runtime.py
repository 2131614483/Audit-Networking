"""统一运行时入口。

用法（在仓库根目录执行）：
  python -m modules.shared.runtime fa_02        # 启动 fa_02 模块
  python -m modules.shared.runtime fa_02 fa_07  # 启动多个（顺序）
"""
from __future__ import annotations

import importlib
import logging
import sys

logger = logging.getLogger("modules.runtime")


def start(slug: str) -> None:
    try:
        mod = importlib.import_module(f"modules.{slug}.main")
    except ModuleNotFoundError as e:
        logger.error("找不到模块 modules.%s.main：%s", slug, e)
        sys.exit(1)
    import uvicorn
    port = getattr(mod, "PORT", 8000)
    logger.info("启动模块 %s 于 0.0.0.0:%d", slug, port)
    uvicorn.run(mod.app, host="0.0.0.0", port=port)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if len(sys.argv) < 2:
        print("用法: python -m modules.shared.runtime <slug> [<slug> ...]  例如 fa_02")
        sys.exit(1)
    for slug in sys.argv[1:]:
        start(slug)


if __name__ == "__main__":
    main()
