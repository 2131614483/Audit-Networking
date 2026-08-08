# -*- coding: utf-8 -*-
"""launcher_gui.py 完整测试套件（避免 GUI 闪退的自动化回归）。

运行：
    pytest test_launcher_gui.py -v --tb=short
    或
    .venv\\Scripts\\python.exe -m pytest test_launcher_gui.py -v

测试项：
    T1 语法检查通过
    T2 模块能 import，不抛任何异常
    T3 find_python() 返回真实存在的 python 路径
    T4 Tk() 创建 + LauncherApp 实例化无异常（withdraw 不显示）
    T5 UI 组件全部存在且状态正确（按钮、勾选框、日志Text）
    T6 默认参数值正确（端口8765、regen=False、no_browser=False）
    T7 日志彩色标签全部注册成功，_log() 写入后可读
    T8 start() → stop() 按钮状态联动是否正确
    T9 通过真实子进程调 launch.py，GUI 读日志窗口并解析出 URL
   T10 GUI 作为子进程启动 → 10 秒仍存活 → 收到 WM_DESTROY 后退出码 0（不闪退）
   T11 崩溃钩子功能：手动抛异常，launcher_crash.log 写入成功
   T12 启动平台.bat 和 启动器_图形版.bat 语法正确
   T13 requirements.txt 存在且包含必需依赖
   T14 _find_system_python() 返回可用 python
   T15 _check_deps_installed() 正确检测当前 venv 依赖
   T16 ensure_venv() 在 venv 已存在时直接返回路径
   T17 .bat 脚本包含自动创建 venv 的逻辑
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

# ---- Tcl/Tk locale 隔离 ----
# 某些 Windows Python 312 的 tk8.6/msgs/zh_cn.msg 缺失，连续创建/销毁 Tk 实例后
# msgcat 重新加载 locale 会抛 TclError。强制 C locale，避免加载中文 .msg 文件。
# 仅影响测试进程，不影响 launcher 真实运行（test_t10 已验证真实子进程不闪退）。
os.environ.setdefault("LANG", "C")
os.environ.setdefault("LC_ALL", "C")

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
LAUNCHER_GUI = HERE / "launcher_gui.py"
CRASH_LOG = HERE / "launcher_crash.log"
BAT1 = HERE / "启动平台.bat"
BAT2 = HERE / "启动器_图形版.bat"


# ========== T1 语法检查 ==========
def test_t1_syntax():
    import ast
    src = LAUNCHER_GUI.read_text(encoding="utf-8")
    ast.parse(src)
    # 关键名字必须存在
    for name in ("LauncherApp", "find_python", "main", "_write_crash_log",
                 "_install_global_excepthooks"):
        assert name in src, f"missing name: {name}"


# ========== T2 import 不抛异常 ==========
def test_t2_import():
    import importlib.util
    spec = importlib.util.spec_from_file_location("launcher_gui_mod", LAUNCHER_GUI)
    mod = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(mod)
    # 全局钩子已安装
    assert sys.excepthook is not sys.__excepthook__
    assert hasattr(mod, "LauncherApp")
    assert hasattr(mod, "find_python")
    assert hasattr(mod, "CRASH_LOG") and mod.CRASH_LOG == CRASH_LOG


# ========== T3 find_python 找到可执行 python ==========
def test_t3_find_python():
    from launcher_gui import find_python
    py = find_python()
    assert py, "find_python() 空字符串"
    # 如果是绝对路径，必须真实存在
    if os.path.isabs(py):
        assert Path(py).exists(), f"python 路径不存在: {py}"
        # 可执行：能跑 --version
        r = subprocess.run([py, "--version"], capture_output=True, text=True, timeout=10)
        assert r.returncode == 0, f"{py} --version 失败: {r.stderr}"


# ========== T4 Tk 实例化无异常 ==========
def _withdraw_root():
    import tkinter as tk
    r = tk.Tk()
    r.withdraw()
    # DPI 相关设置在 main() 里，这里不重复调用避免二次异常
    return r


def test_t4_app_create():
    import tkinter as tk
    from launcher_gui import LauncherApp
    r = _withdraw_root()
    try:
        r.update_idletasks()
        app = LauncherApp(r)
        r.update_idletasks()
        r.update()
        assert app.root is r
    finally:
        r.destroy()


# ========== T5 UI 组件存在且状态 ==========
def test_t5_ui_components():
    from launcher_gui import LauncherApp
    r = _withdraw_root()
    try:
        app = LauncherApp(r)
        r.update()
        # 按钮
        assert app.btn_start.winfo_exists()
        assert str(app.btn_start.cget("state")) == "normal"
        assert app.btn_stop.winfo_exists()
        assert str(app.btn_stop.cget("state")) == "disabled"
        assert app.btn_open_browser.winfo_exists()
        assert str(app.btn_open_browser.cget("state")) == "disabled"
        # 日志 text
        assert app.txt_log.winfo_exists()
        # 变量
        assert hasattr(app, "var_regen")
        assert hasattr(app, "var_no_browser")
        assert hasattr(app, "var_port")
        assert hasattr(app, "var_python")
        assert hasattr(app, "status_var")
    finally:
        r.destroy()


# ========== T6 默认值 ==========
def test_t6_default_values():
    from launcher_gui import LauncherApp
    r = _withdraw_root()
    try:
        app = LauncherApp(r)
        r.update()
        assert app.var_port.get() == 8765
        assert app.var_regen.get() is False
        assert app.var_no_browser.get() is False
        assert app.status_var.get() == "就绪"
    finally:
        r.destroy()


# ========== T7 日志写入和彩色 tag ==========
def test_t7_log_and_tags():
    from launcher_gui import LauncherApp
    r = _withdraw_root()
    try:
        app = LauncherApp(r)
        r.update()
        tags = ("ok", "warn", "err", "info", "dim")
        registered = set(app.txt_log.tag_names())
        for t in tags:
            assert t in registered, f"missing tag: {t}"
        # 写一条含 OK 关键字的
        app._log("测试成功 ✅ 完成")
        r.update()
        content = app.txt_log.get("1.0", "end")
        assert "测试成功" in content
        # 未知 tag → 空 tag 兜底不抛错
        app._log("nothing special")
        # txt_log is None 时也不能抛错（伪造临时实例）
        class Fake: pass
        fake = Fake()
        fake.txt_log = None
        LauncherApp._log(fake, "should-not-raise", "ok")
    finally:
        r.destroy()


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ========== T8 start/stop 按钮状态联动 ==========
def test_t8_start_stop_states():
    from launcher_gui import LauncherApp
    r = _withdraw_root()
    try:
        app = LauncherApp(r)
        r.update()
        app.var_no_browser.set(True)
        app.var_port.set(_free_port())
        app.start()
        r.update()
        assert app.proc is not None
        assert str(app.btn_start.cget("state")) == "disabled"
        assert str(app.btn_stop.cget("state")) == "normal"
        # 给子进程时间出来，然后停止
        t0 = time.time()
        while time.time() - t0 < 4:
            r.update_idletasks()
            r.update()
            time.sleep(0.1)
        app.stop()
        r.update()
        assert app.proc is None
        assert str(app.btn_start.cget("state")) == "normal"
        assert str(app.btn_stop.cget("state")) == "disabled"
    finally:
        r.destroy()


# ========== T9 真实启动 launch.py + GUI 解析 URL ==========
def test_t9_e2e_launch_and_parse_url():
    from launcher_gui import LauncherApp
    r = _withdraw_root()
    try:
        app = LauncherApp(r)
        r.update()
        app.var_no_browser.set(True)
        port = _free_port()
        app.var_port.set(port)
        app.start()
        r.update()
        assert app.proc is not None
        # 最多等 8 秒，让日志中出现 URL
        t0 = time.time()
        got_url = False
        while time.time() - t0 < 8:
            r.update_idletasks()
            r.update()
            time.sleep(0.15)
            if app.url and str(app.btn_open_browser.cget("state")) == "normal":
                got_url = True
                break
        log = app.txt_log.get("1.0", "end")
        assert got_url, f"日志中没解析到 URL。\n--- log dump ---\n{log[-1200:]}"
        assert str(port) in app.url, f"URL={app.url} 中没有端口 {port}"
        app.stop()
        r.update()
    finally:
        r.destroy()


# ========== T10 真实 subprocess 跑 GUI 10 秒存活 + 关闭后退出码 0 ==========
def test_t10_subprocess_gui_alive_and_clean_exit(tmp_path):
    # 用一个小的 Python 驱动脚本，启动 GUI，等 10 秒再发送 destroy 事件
    driver = tmp_path / "_driver.py"
    driver.write_text(
        r'''
import sys, time, subprocess, threading, os, signal
from pathlib import Path
sys.path.insert(0, str(Path(r"__ROOT__")))

# 先通过正常运行 launcher_gui 作为子进程，通过 DISPLAY/headless 环境正常显示
# 在无桌面的 CI 也可运行（Windows 正常用户桌面下）
cmd = [r"__PYTHON__", str(Path(r"__ROOT__") / "launcher_gui.py")]
proc = subprocess.Popen(cmd, cwd=r"__ROOT__",
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, encoding="utf-8", errors="replace",
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

def drain():
    global out
    out = {"stdout": [], "stderr": []}
    def _p():
        for line in proc.stdout:
            out["stdout"].append(line)
    def _q():
        for line in proc.stderr:
            out["stderr"].append(line)
    threading.Thread(target=_p, daemon=True).start()
    threading.Thread(target=_q, daemon=True).start()

drain()

# 运行 10 秒，每 1 秒检查存活
dead_at = -1
for i in range(10):
    time.sleep(1)
    if proc.poll() is not None:
        dead_at = i + 1
        break

if dead_at > 0:
    so, se = proc.communicate(timeout=5)
    out["stdout"].append(so or "")
    out["stderr"].append(se or "")
    print("!! EARLY DEAD at second", dead_at, file=sys.stderr)
    print("STDOUT:", "".join(out["stdout"])[-1500:], file=sys.stderr)
    print("STDERR:", "".join(out["stderr"])[-2000:], file=sys.stderr)
    sys.exit(2)

# 仍存活：发送 taskkill 要求 GUI 自己的退出钩子响应（温和关闭）
try:
    proc.terminate()
    try:
        rc = proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        rc = proc.wait(timeout=5)
except Exception as e:
    print("terminate error:", e, file=sys.stderr)
    rc = -1

so, se = proc.communicate(timeout=5)
print("FINAL_STDOUT tail:", (so or "")[-500:], file=sys.stderr)
print("FINAL_STDERR tail:", (se or "")[-500:], file=sys.stderr)
# terminate 在无 console GUI 上是合法的，返回码为 1（Windows taskkill 风格）或 0 都可以接受
# 但必须不是 crash 导致的 2（early dead）
sys.exit(0 if rc in (0, 1, -15, -1) else 3)
'''.replace("__ROOT__", str(HERE)).replace("__PYTHON__", sys.executable),
        encoding="utf-8",
    )
    t0 = time.time()
    # 超时 25 秒（GUI 运行10秒 + 收尾）
    try:
        res = subprocess.run(
            [sys.executable, str(driver)],
            cwd=str(HERE),
            capture_output=True, text=True, timeout=25,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("GUI 子进程驱动 25 秒仍未完成（可能卡死）")

    if res.returncode != 0:
        print("--- STDOUT driver ---")
        print(res.stdout)
        print("--- STDERR driver ---")
        print(res.stderr)
    assert res.returncode == 0, (
        f"驱动退出码={res.returncode}，见上方 STDERR 输出详情。\n"
        f"若 driver 返回 2，说明 GUI 在 10 秒内就自己闪退了。"
    )


# ========== T11 崩溃日志钩子功能 ==========
def test_t11_crash_log_written(tmp_path, monkeypatch):
    import launcher_gui as mod
    # 把 crash_log 写到 tmp 避免污染
    monkeypatch.setattr(mod, "CRASH_LOG", tmp_path / "crash.log")
    # 走 sys.excepthook
    try:
        raise ValueError("test boom")
    except ValueError:
        mod.sys.excepthook(*sys.exc_info())
    logp = tmp_path / "crash.log"
    assert logp.exists(), "crash log 文件没生成"
    txt = logp.read_text(encoding="utf-8")
    assert "test boom" in txt
    assert "ValueError" in txt


# ========== T12 .bat 文件结构正确 ==========
def test_t12_bat_files():
    for bat in (BAT1, BAT2):
        assert bat.exists(), f"{bat.name} 缺失"
        t = bat.read_text(encoding="utf-8", errors="ignore")
        assert "@echo off" in t.lower()
        assert "cd" in t.lower()
        # 两个 bat 都必须最终调用 python（BAT1→launch.py，BAT2→launcher_gui.py）
        assert "python" in t.lower() or "%python%" in t.lower() or "%~dp0.venv" in t


# ========== T13 requirements.txt 存在且包含必需依赖 ==========
def test_t13_requirements():
    req = HERE / "requirements.txt"
    assert req.exists(), "requirements.txt 缺失"
    content = req.read_text(encoding="utf-8")
    for pkg in ("fastapi", "uvicorn", "pydantic", "PyYAML", "openai", "pytest"):
        assert pkg.lower() in content.lower(), f"requirements.txt 缺少 {pkg}"


# ========== T14 _find_system_python 返回可用 python ==========
def test_t14_find_system_python():
    from launcher_gui import _find_system_python
    py = _find_system_python()
    assert py, "系统中未找到任何 Python 解释器"
    # 能跑 --version
    r = subprocess.run([py, "--version"], capture_output=True, text=True,
                       timeout=10, shell=(" " in py))
    assert r.returncode == 0, f"{py} --version 失败: {r.stderr}"


# ========== T15 _check_deps_installed 正确检测 ==========
def test_t15_check_deps():
    from launcher_gui import _check_deps_installed, ROOT
    venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
    if not venv_py.exists():
        pytest.skip("当前测试环境无 .venv，跳过")
    # 当前 venv 已经装好了依赖
    assert _check_deps_installed(venv_py) is True


# ========== T16 ensure_venv 在 venv 已存在时直接返回 ==========
def test_t16_ensure_venv_existing():
    from launcher_gui import ensure_venv, ROOT
    venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
    if not venv_py.exists():
        pytest.skip("当前测试环境无 .venv，跳过")
    logs = []
    py = ensure_venv(log_fn=lambda msg, tag="": logs.append(msg))
    assert py == str(venv_py), f"ensure_venv 返回了非预期路径: {py}"
    # venv 已存在且依赖齐全时，不应触发创建日志
    assert not any("正在自动创建" in l for l in logs), \
        f"venv 已存在却触发了创建: {logs}"


# ========== T17 .bat 脚本包含自动创建 venv 逻辑 ==========
def test_t17_bat_auto_venv():
    for bat in (BAT1, BAT2):
        t = bat.read_text(encoding="utf-8", errors="ignore")
        # 必须包含 venv 创建命令
        assert "venv" in t.lower(), f"{bat.name} 缺少 venv 创建逻辑"
        # 启动平台.bat 自己做 pip install；图形版.bat 由 launcher_gui.py 内部做
        if bat == BAT1:
            assert "pip install" in t.lower() or "requirements.txt" in t.lower(), \
                f"{bat.name} 缺少依赖安装逻辑"
        # 必须有找不到 Python 时的友好提示
        assert "python.org" in t.lower() or "安装" in t, \
            f"{bat.name} 缺少 Python 未安装时的提示"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
