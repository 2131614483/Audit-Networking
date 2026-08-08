"""一键创建家族虚拟环境。

用法：
  python modules/venvs/setup_venvs.py ml          # 只建 ml
  python modules/venvs/setup_venvs.py all         # 建全部家族
  python modules/venvs/setup_venvs.py thin ml kg  # 建指定若干
"""
from __future__ import annotations

import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # 仓库根
VENV_DIR = ROOT / ".venvs"
REQ_DIR = Path(__file__).resolve().parent

ALL_FAMILIES = ["thin", "ml", "kg", "llm", "cv", "streaming", "rpa", "blockchain", "federation"]


def create(family: str) -> None:
    target = VENV_DIR / family
    if target.exists():
        print(f"[skip] {target} 已存在")
        return
    print(f"[create] {target}")
    venv.create(target, with_pip=True, clear=False)
    pip = str(target / "Scripts" / "pip.exe") if sys.platform == "win32" else str(target / "bin" / "pip")
    req = REQ_DIR / f"{family}-requirements.txt"
    if req.exists():
        print(f"[install] {req.name}")
        subprocess.check_call([pip, "install", "-r", str(req)])
    print(f"[done] 激活: {target}/Scripts/activate  或  source {target}/bin/activate")


def main() -> None:
    args = sys.argv[1:] or ["thin"]
    fams = ALL_FAMILIES if args[0] == "all" else args
    for f in fams:
        if f not in ALL_FAMILIES:
            print(f"[warn] 未知家族 {f}，跳过")
            continue
        create(f)


if __name__ == "__main__":
    main()
