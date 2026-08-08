# -*- coding: utf-8 -*-
"""智能审计可视化平台 — 图形化启动器 (GUI)

功能：
1. 自动探测虚拟环境 Python 解释器
2. 勾选框设置启动参数：--regen / --no-browser / 自定义端口
3. 实时彩色日志窗口显示 launch.py 输出
4. 一键"启动 / 停止 / 打开浏览器 / 打开项目目录"
5. 状态栏实时显示运行状态和监听 URL

用法：
    双击启动器.bat 或 运行：python launcher_gui.py
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import (
    BooleanVar, END, IntVar, StringVar, Tk, Text, filedialog,
    messagebox, ttk,
)

ROOT = Path(__file__).resolve().parent
LAUNCH_PY = ROOT / "launch.py"
WEB_DIR = ROOT / "web"
DATA_PATH = ROOT / "demo" / "audit_data.json"
CRASH_LOG = ROOT / "launcher_crash.log"

LOG_COLORS = {
    "INFO": "#2563eb",
    "OK": "#059669",
    "WARN": "#d97706",
    "ERR": "#dc2626",
    "DEFAULT": "#1f2937",
}


# ====== 全局闪退防护：任何未捕获异常都写入 launcher_crash.log ======
def _write_crash_log(title: str, exc_info) -> Path:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tb = "".join(traceback.format_exception(*exc_info))
    with open(CRASH_LOG, "a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 60}\n[{ts}] {title}\n{'=' * 60}\n{tb}\n")
    return CRASH_LOG


def _install_global_excepthooks():
    def on_except(etype, value, tb):
        try:
            path = _write_crash_log("未捕获异常 (sys.excepthook)", (etype, value, tb))
            # 尝试弹框提示（如果有 Tk）
            try:
                from tkinter import Tk
                r = Tk()
                r.withdraw()
                messagebox.showerror(
                    "启动器崩溃",
                    f"程序发生未捕获异常，错误日志已写入：\n{path}\n\n"
                    f"{etype.__name__}: {value}"
                )
                r.destroy()
            except Exception:
                pass
        finally:
            # 原默认行为也执行（打印到控制台）
            sys.__excepthook__(etype, value, tb)
    sys.excepthook = on_except


_install_global_excepthooks()


def find_python() -> str:
    """返回虚拟环境的 python.exe 路径（不存在则返回空字符串）。"""
    venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_py.exists():
        return str(venv_py)
    return ""


def _find_system_python() -> str:
    """在系统中寻找可用的 Python 解释器（用于创建 venv）。"""
    for candidate in ("python", "py -3", "python3"):
        try:
            r = subprocess.run(
                f"{candidate} --version",
                capture_output=True, text=True, shell=True, timeout=5
            )
            if r.returncode == 0:
                # "py -3" 需要拆分
                return candidate.split()[0] if " " in candidate else candidate
        except Exception:
            continue
    return ""


def ensure_venv(log_fn=None) -> str:
    """确保虚拟环境存在。不存在则自动创建并安装依赖。

    Args:
        log_fn: 可选的回调函数 (str) -> None，用于输出进度日志。

    Returns:
        虚拟环境的 python.exe 路径，失败返回空字符串。
    """
    venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_py.exists():
        # venv 已存在，检查依赖是否安装
        if _check_deps_installed(venv_py):
            return str(venv_py)
        # 依赖缺失，重新安装
        if log_fn:
            log_fn("📦 检测到依赖缺失，正在安装...", "warn")
        _pip_install(venv_py, log_fn)
        return str(venv_py)

    # ---- venv 不存在，自动创建 ----
    if log_fn:
        log_fn("🔧 未找到虚拟环境，正在自动创建 .venv ...", "warn")

    sys_py = _find_system_python()
    if not sys_py:
        if log_fn:
            log_fn("❌ 系统中未找到 Python 解释器，请先安装 Python 3.10+", "err")
        return ""

    # 创建 venv
    if log_fn:
        log_fn(f"   使用系统 Python: {sys_py}", "info")
        log_fn("   正在创建虚拟环境（可能需要 10-30 秒）...", "info")

    try:
        r = subprocess.run(
            [sys_py, "-m", "venv", str(ROOT / ".venv")],
            capture_output=True, text=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if r.returncode != 0:
            if log_fn:
                log_fn(f"❌ 创建虚拟环境失败: {r.stderr}", "err")
            return ""
    except Exception as e:
        if log_fn:
            log_fn(f"❌ 创建虚拟环境异常: {e}", "err")
        return ""

    if not venv_py.exists():
        if log_fn:
            log_fn("❌ 虚拟环境创建后仍找不到 python.exe", "err")
        return ""

    if log_fn:
        log_fn("✅ 虚拟环境创建成功！", "ok")

    # 安装依赖
    _pip_install(venv_py, log_fn)

    return str(venv_py)


def _check_deps_installed(venv_py: Path) -> bool:
    """检查关键依赖是否已安装。

    注意：openai 等大包冷 import 可能需要 5-10 秒，timeout 设为 30 秒
    避免在冷启动/系统繁忙时误判为「依赖未装」而触发无谓的重新 pip install。
    """
    try:
        r = subprocess.run(
            [str(venv_py), "-c",
             "import fastapi, uvicorn, pydantic, yaml, openai; print('ok')"],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return r.returncode == 0 and "ok" in r.stdout
    except Exception:
        return False


def _pip_install(venv_py: Path, log_fn=None) -> bool:
    """用 venv 的 pip 安装 requirements.txt 中的依赖。"""
    req_file = ROOT / "requirements.txt"
    if not req_file.exists():
        if log_fn:
            log_fn("⚠️  未找到 requirements.txt，跳过依赖安装", "warn")
        return False

    if log_fn:
        log_fn("📦 正在安装依赖包（首次可能需要 1-3 分钟）...", "info")

    try:
        r = subprocess.run(
            [str(venv_py), "-m", "pip", "install", "-r", str(req_file), "--quiet"],
            capture_output=True, text=True, timeout=300,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if r.returncode != 0:
            if log_fn:
                log_fn(f"❌ 依赖安装失败: {r.stderr[-500:]}", "err")
            return False
        if log_fn:
            log_fn("✅ 依赖安装完成！", "ok")
        return True
    except subprocess.TimeoutExpired:
        if log_fn:
            log_fn("❌ 依赖安装超时（5分钟），请检查网络后重试", "err")
        return False
    except Exception as e:
        if log_fn:
            log_fn(f"❌ 依赖安装异常: {e}", "err")
        return False


class LauncherApp:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title("🚀 智能审计可视化平台 — 启动器")
        self.root.geometry("760x560")
        self.root.minsize(700, 500)

        self.proc: subprocess.Popen | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.url = ""
        self._env_ready = False  # venv 创建完成后置 True

        self._build_style()
        self._build_ui()
        self._poll_log()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # ---- 后台线程：自动检查/创建虚拟环境 ----
        threading.Thread(target=self._ensure_env_async, daemon=True).start()

    # ------------------------------------------------------------------ UI
    def _build_style(self):
        style = ttk.Style()
        # 主题配置：逐个 try，不支持就跳过，绝不因为主题/字体问题闪退
        themes = ["clam", "vista", "default", "classic"]
        for t in themes:
            try:
                style.theme_use(t)
                break
            except Exception:
                continue
        # 字体容错：先尝试微软雅黑，回退到系统默认安全字体
        for title_font in [
            ("Microsoft YaHei", 14, "bold"),
            ("微软雅黑", 14, "bold"),
            ("SimHei", 14, "bold"),
            ("TkDefaultFont", 14, "bold"),
            ("TkDefaultFont", 14),
        ]:
            try:
                style.configure("Title.TLabel", font=title_font)
                break
            except Exception:
                continue
        for sec_font in [
            ("Microsoft YaHei", 10, "bold"),
            ("微软雅黑", 10, "bold"),
            ("SimHei", 10, "bold"),
            ("TkDefaultFont", 10, "bold"),
        ]:
            try:
                style.configure("Section.TLabelframe.Label", font=sec_font)
                break
            except Exception:
                continue
        for btn_font in [
            ("Microsoft YaHei", 11, "bold"),
            ("微软雅黑", 11, "bold"),
            ("SimHei", 11, "bold"),
            ("TkDefaultFont", 11),
        ]:
            try:
                style.configure("Start.TButton", font=btn_font, padding=(18, 8))
                style.configure("Stop.TButton", font=btn_font, padding=(18, 8))
                break
            except Exception:
                continue

    def _build_ui(self):
        pad = {"padx": 12, "pady": 8}

        # ---- 顶部标题
        header = ttk.Frame(self.root)
        header.pack(fill="x", **pad)
        ttk.Label(header, text="🚀 智能审计可视化平台",
                  style="Title.TLabel").pack(side="left")

        self.status_var = StringVar(value="就绪")
        ttk.Label(header, textvariable=self.status_var,
                  foreground="#059669", anchor="e").pack(side="right", fill="x", expand=True)

        # ---- 参数设置框
        frm_params = ttk.LabelFrame(self.root, text=" 启动参数 ",
                                    style="Section.TLabelframe")
        frm_params.pack(fill="x", padx=12, pady=(0, 8))

        self.var_regen = BooleanVar(value=False)
        self.var_no_browser = BooleanVar(value=False)
        self.var_port = IntVar(value=8765)
        self.var_python = StringVar(value=find_python())

        row1 = ttk.Frame(frm_params)
        row1.pack(fill="x", padx=10, pady=8)

        ttk.Label(row1, text="Python:").grid(row=0, column=0, sticky="w")
        py_entry = ttk.Entry(row1, textvariable=self.var_python, width=52)
        py_entry.grid(row=0, column=1, sticky="we", padx=(6, 6))
        ttk.Button(row1, text="选择…", command=self._choose_python).grid(row=0, column=2)
        row1.columnconfigure(1, weight=1)

        row2 = ttk.Frame(frm_params)
        row2.pack(fill="x", padx=10, pady=(0, 10))

        ttk.Checkbutton(row2, text="🔄 重新生成审计数据 (--regen)",
                        variable=self.var_regen).pack(side="left", padx=(0, 18))
        ttk.Checkbutton(row2, text="🚫 不自动打开浏览器 (--no-browser)",
                        variable=self.var_no_browser).pack(side="left", padx=(0, 18))

        ttk.Label(row2, text="端口:").pack(side="left", padx=(24, 4))
        ttk.Spinbox(row2, from_=1024, to=65535, textvariable=self.var_port,
                    width=6).pack(side="left")

        # ---- 操作按钮
        frm_btns = ttk.Frame(self.root)
        frm_btns.pack(fill="x", padx=12, pady=(0, 6))

        self.btn_start = ttk.Button(frm_btns, text="▶ 启动平台",
                                    style="Start.TButton", command=self.start)
        self.btn_start.pack(side="left")

        self.btn_stop = ttk.Button(frm_btns, text="■ 停止",
                                   style="Stop.TButton", command=self.stop,
                                   state="disabled")
        self.btn_stop.pack(side="left", padx=8)

        ttk.Separator(frm_btns, orient="vertical").pack(side="left", fill="y",
                                                         padx=14)

        self.btn_open_browser = ttk.Button(frm_btns, text="🌐 打开浏览器",
                                           command=self.open_browser,
                                           state="disabled")
        self.btn_open_browser.pack(side="left", padx=4)

        ttk.Button(frm_btns, text="📂 项目目录",
                   command=self.open_project_dir).pack(side="left", padx=4)
        ttk.Button(frm_btns, text="🧪 运行模块测试",
                   command=self.run_tests).pack(side="left", padx=4)
        ttk.Button(frm_btns, text="🗑 清空日志",
                   command=self.clear_log).pack(side="right", padx=4)

        # ---- 日志窗口
        frm_log = ttk.LabelFrame(self.root, text=" 运行日志 ",
                                 style="Section.TLabelframe")
        frm_log.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.txt_log = Text(frm_log, height=16, wrap="word",
                            font=("Consolas", 10), bg="#0f172a",
                            fg="#e2e8f0", insertbackground="#e2e8f0",
                            relief="flat", padx=10, pady=8)
        self.txt_log.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        sb = ttk.Scrollbar(frm_log, command=self.txt_log.yview)
        sb.pack(side="right", fill="y", pady=6)
        self.txt_log.configure(yscrollcommand=sb.set)

        # 颜色标签
        for tag, color in [
            ("ok", "#34d399"), ("warn", "#fbbf24"),
            ("err", "#f87171"), ("info", "#60a5fa"),
            ("dim", "#94a3b8"),
        ]:
            self.txt_log.tag_configure(tag, foreground=color)

        self._log("欢迎使用智能审计可视化平台启动器！", "ok")
        py = self.var_python.get() or "❌ 未找到，正在自动创建..."
        self._log(f"Python 解释器: {py}", "info")
        self._log(f"项目目录: {ROOT}", "dim")
        if not self.var_python.get():
            self._log("⏳ 正在后台自动创建虚拟环境，请稍候...", "warn")

    # --------------------------------------------------- venv 自动创建
    def _ensure_env_async(self):
        """后台线程：自动检查/创建虚拟环境，完成后更新 UI。"""
        def log(msg, tag=""):
            self.log_queue.put(f"[ENV] {msg}")

        py = ensure_venv(log_fn=log)
        if py:
            self._env_ready = True
            self.log_queue.put(f"[ENV_DONE] {py}")
        else:
            self._env_ready = False
            self.log_queue.put("[ENV_FAIL]")

    # ------------------------------------------------------------ Operations
    def _choose_python(self):
        path = filedialog.askopenfilename(
            title="选择 Python.exe",
            filetypes=[("Python 解释器", "python.exe"), ("可执行文件", "*.exe")],
            initialdir=str(ROOT),
        )
        if path:
            self.var_python.set(path)

    def start(self):
        if self.proc and self.proc.poll() is None:
            return
        # 环境还没准备好（正在创建 venv 或安装依赖）
        if not self._env_ready:
            py = self.var_python.get().strip()
            if not py:
                messagebox.showwarning(
                    "环境准备中",
                    "虚拟环境正在自动创建中，请等待日志显示「✅ 依赖安装完成」后再启动。"
                )
                return
        py = self.var_python.get().strip()
        if not py:
            messagebox.showerror("错误", "Python 解释器路径为空！\n请手动选择或等待虚拟环境创建完成。")
            return
        if not Path(py).exists():
            messagebox.showerror("错误", f"Python 解释器不存在:\n{py}")
            return
        if not LAUNCH_PY.exists():
            messagebox.showerror("错误", f"找不到 launch.py:\n{LAUNCH_PY}")
            return

        cmd = [py, str(LAUNCH_PY), "--port", str(self.var_port.get())]
        if self.var_regen.get():
            cmd.append("--regen")
        if self.var_no_browser.get():
            cmd.append("--no-browser")
        # 即使勾选了自动打开，也禁掉 GUI 自己去开，因为我们有按钮可控
        cmd.append("--no-browser")

        try:
            # PYTHONUNBUFFERED=1 保证 launch.py print 输出即时写 stdout，
            # 不能让缓冲等到进程结束才 flush（否则 GUI 日志会一直空）
            child_env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
            self.proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                bufsize=1, env=child_env,
            )
        except Exception as e:
            messagebox.showerror("启动失败", str(e))
            return

        self._log(f"▶ 启动命令: {' '.join(cmd)}", "info")
        self._log("服务器进程已启动 (PID=%d)，等待就绪..." % self.proc.pid, "ok")

        self.status_var.set("🟢 运行中")
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")

        threading.Thread(target=self._read_stdout, daemon=True).start()

    def stop(self):
        killed = False
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=2)
                killed = True
                self._log("■ 服务器已停止", "warn")
            except Exception as e:
                self._log(f"停止失败: {e}", "err")
        self.proc = None
        self.url = ""
        self.status_var.set("就绪" if not killed else "已停止")
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.btn_open_browser.config(state="disabled")

    def open_browser(self):
        if self.url:
            webbrowser.open(self.url)
        else:
            # 还没拿到地址时猜一个
            webbrowser.open(f"http://127.0.0.1:{self.var_port.get()}/")

    def open_project_dir(self):
        try:
            os.startfile(str(ROOT))  # type: ignore[attr-defined]
        except Exception:
            try:
                subprocess.Popen(["explorer", str(ROOT)])
            except Exception as e:
                self._log(f"打开目录失败: {e}", "err")

    def run_tests(self):
        py = self.var_python.get().strip()
        if not py:
            messagebox.showerror("错误", "请先选择 Python 解释器！")
            return
        self._log("🧪 开始运行模块测试...", "info")

        def worker():
            try:
                child_env = dict(os.environ, PYTHONUNBUFFERED="1",
                                 PYTHONIOENCODING="utf-8")
                p = subprocess.Popen(
                    [py, "-m", "pytest", "demo/test_all_modules.py", "-v", "--tb=short"],
                    cwd=str(ROOT),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    bufsize=1, env=child_env,
                )
                for line in p.stdout or []:
                    self.log_queue.put(line.rstrip())
                p.wait()
                self.log_queue.put(
                    f"🧪 测试退出码: {p.returncode}（0 表示全部通过）"
                )
            except Exception as e:
                self.log_queue.put(f"[ERR] 运行测试失败: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def clear_log(self):
        self.txt_log.delete("1.0", END)

    # ----------------------------------------------------- log & lifecycle
    def _read_stdout(self):
        proc = self.proc
        if proc is None:
            return
        try:
            if proc.stdout:
                for line in proc.stdout:
                    self.log_queue.put(line.rstrip())
        except Exception:
            pass
        # for 循环结束 = stdout 关闭 = 进程已退出
        # 用 proc.poll() 确认进程真的退出了，才发 PROCESS_EXIT
        # 避免因 stdout 缓冲问题误判导致 stop() 被错误触发
        try:
            proc.wait(timeout=10)
        except Exception:
            pass
        if proc.poll() is not None:
            self.log_queue.put(f"[PROCESS_EXIT] code={proc.returncode}")

    def _poll_log(self):
        try:
            while True:
                line = self.log_queue.get_nowait()
                if line.startswith("[PROCESS_EXIT]"):
                    if self.proc:
                        self._log(f"■ 服务器进程退出 ({line})", "warn")
                        self.stop()
                    continue
                # 虚拟环境创建完成
                if line.startswith("[ENV_DONE]"):
                    py_path = line.replace("[ENV_DONE]", "").strip()
                    self.var_python.set(py_path)
                    self._env_ready = True
                    self.status_var.set("就绪 · 环境已就绪")
                    self._log(f"✅ 虚拟环境就绪: {py_path}", "ok")
                    continue
                if line == "[ENV_FAIL]":
                    self._env_ready = False
                    self.status_var.set("❌ 环境创建失败")
                    self._log("❌ 虚拟环境创建失败，请手动安装 Python 后重试", "err")
                    continue
                # 去掉 [ENV] 前缀
                if line.startswith("[ENV] "):
                    self._log(line[6:])
                    continue
                # 从打印内容中自动提取 URL
                if "http://127.0.0.1:" in line and not self.url:
                    for part in line.split():
                        if part.startswith("http://127.0.0.1:"):
                            self.url = part.strip()
                            self.btn_open_browser.config(state="normal")
                            self.status_var.set(f"🟢 运行中 · {self.url}")
                            # 如果用户没勾选"不自动打开"，此处帮他开
                            if not self.var_no_browser.get():
                                self.root.after(500, self.open_browser)
                            break
                self._log(line)
        except queue.Empty:
            pass
        self.root.after(120, self._poll_log)

    def _log(self, text: str, tag: str = ""):
        # 先写到 stderr（至少确保有回退输出）
        print(f"[launcher] {text}", file=sys.stderr, flush=True)
        # txt_log 还没构建好就先跳过
        txt_log = getattr(self, "txt_log", None)
        if txt_log is None:
            return
        try:
            if not tag:
                low = text.lower()
                if any(k in low for k in ("错误", "失败", "error", "exception",
                                           "fail", "❌", "[err]")):
                    tag = "err"
                elif any(k in low for k in ("✅", "ok", "成功", "通过", "🟢",
                                            "[ ok ]", "start", "启动")):
                    tag = "ok"
                elif any(k in low for k in ("warn", "⚠", "警告", "占用",
                                            "改用", "[warn]")):
                    tag = "warn"
                elif any(k in text for k in (" ", "─", "│", "═", "╔", "╚",
                                              "║", "╗", "╝")) and "http" not in text:
                    tag = "dim"
                else:
                    tag = ""
            # 如果 tag 还没注册就用空标签（防止 Tk 报错）
            if tag and tag not in txt_log.tag_names():
                tag = ""
            txt_log.insert(END, text + "\n", tag)
            txt_log.see(END)
        except Exception as e:
            # 日志写入失败绝对不能引发闪退，至多打印到 stderr
            print(f"[launcher] _log 写入失败: {e}", file=sys.stderr, flush=True)

    def _on_close(self):
        try:
            if self.proc and self.proc.poll() is None:
                if not messagebox.askyesno("确认退出", "服务器仍在运行，是否停止并退出？"):
                    return
                self.stop()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass


def main():
    # ===== 启动前先清除旧的 crash log（可选）但保留内容追加到新记录 =====
    # ===== DPI 配置（完全容错，任何 Win 版本都不能在这里崩）=====
    try:
        from ctypes import windll, WinError
        try:
            # Win10+ 推荐
            windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError, WinError):  # type: ignore[misc]
            try:
                # 老版本 Vista+ fallback
                windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    except Exception:
        pass

    root = None
    try:
        root = Tk()

        # ===== Tk 主循环里的回调异常也必须捕获（闪退最大来源）=====
        def on_tk_error(*args):
            # 写崩溃日志，但不递归调用自身（旧代码调 dr.report_callback_exception
            # 导致无限递归 → 栈溢出 → GUI 闪退）
            try:
                if len(args) == 3:
                    etype, value, tb = args
                else:
                    etype, value, tb = type(args[0]), args[0], None
                tb_text = "".join(traceback.format_exception(etype, value, tb)) if tb else \
                    f"{etype}: {value}"
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with open(CRASH_LOG, "a", encoding="utf-8") as f:
                    f.write(
                        f"\n{'=' * 60}\n[{ts}] Tk callback error\n"
                        f"{'=' * 60}\n{tb_text}\n"
                    )
            except Exception:
                pass
        try:
            root.report_callback_exception = on_tk_error
        except Exception:
            pass

        LauncherApp(root)
        root.mainloop()
    except Exception:
        try:
            path = _write_crash_log("GUI 主流程崩溃", sys.exc_info())
            # 没有窗口上下文的情况下，弹 messagebox 容易再次崩，直接打印 + 控制台暂停信息
            print(f"\n[启动器] 崩溃日志已写入: {path}", file=sys.stderr, flush=True)
        except Exception:
            traceback.print_exc()
        # 让双击启动的用户有机会看到
        if root is not None:
            try:
                root.withdraw()
                messagebox.showerror("启动失败", f"程序发生错误，崩溃日志已写入：\n{CRASH_LOG}")
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()
