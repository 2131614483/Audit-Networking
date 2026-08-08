"""智能审计可视化平台 —— 启动器

功能：
1. 检查审计数据是否存在，不存在则自动生成
2. 启动本地 HTTP 服务器（提供 web 页面 + API 数据接口）
3. 自动打开浏览器

用法:
    python launch.py              # 默认端口 8765
    python launch.py --port 9000  # 指定端口
    python launch.py --regen      # 重新运行审计生成数据
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import shutil
import socketserver
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
DATA_PATH = ROOT / "demo" / "audit_data.json"
# 兜底静态数据文件：前端 fetch("audit_data.json") 能直接在 web/ 目录里找到
WEB_DATA_BACKUP = WEB_DIR / "audit_data.json"


def ensure_data(regen: bool = False) -> bool:
    """确保审计数据存在，必要时重新生成。生成后同步一份到 web/ 目录做兜底。"""
    if DATA_PATH.exists() and not regen:
        _sync_web_backup()
        return True

    print("审计数据不存在，正在生成...")
    sys.path.insert(0, str(ROOT))
    try:
        from demo.run_audit_report import main as run_audit
        run_audit()
        ok = DATA_PATH.exists()
        if ok:
            _sync_web_backup()
        return ok
    except Exception as e:
        print(f"生成审计数据失败: {e}")
        return False


def _sync_web_backup() -> None:
    """把 demo/audit_data.json 复制到 web/audit_data.json 作为静态兜底。"""
    try:
        if DATA_PATH.exists():
            shutil.copyfile(DATA_PATH, WEB_DATA_BACKUP)
    except Exception as e:
        print(f"[warn] 同步静态数据文件失败: {e}")


class AuditHandler(http.server.SimpleHTTPRequestHandler):
    """自定义请求处理器：web 静态文件 + /api/audit_data 接口。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self):
        if self.path == "/api/audit_data":
            self._serve_api()
        elif self.path == "/" or self.path == "":
            self.path = "/index.html"
            super().do_GET()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/ai_summary":
            self._serve_ai_summary()
        else:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"not found"}')

    def _serve_ai_summary(self):
        """POST /api/ai_summary — 返回 DeepSeek AI 生成的发现总结。"""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(body)
        except Exception as e:
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": f"bad request: {e}"}).encode("utf-8"))
            return

        slug = payload.get("slug", "")
        finding = payload.get("finding", {})
        source_records = payload.get("source_records") or finding.get("source_records", {})

        # 导入并调用 DeepSeek 客户端
        try:
            import sys
            sys.path.insert(0, str(ROOT))
            from modules.shared.deepseek_client import call_ai_audit_summary_sync
            summary = call_ai_audit_summary_sync(slug, finding, source_records)
        except Exception as e:
            summary = f"⚠️ AI 总结服务异常：{e}"

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps({"summary": summary}, ensure_ascii=False).encode("utf-8"))

    def _serve_api(self):
        try:
            with open(DATA_PATH, encoding="utf-8") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data.encode("utf-8"))
        except FileNotFoundError:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"audit_data.json not found"}')

    def log_message(self, *args):
        # 静默日志（取消注释可开启）
        pass


def find_free_port(preferred: int) -> int:
    """尝试使用首选端口，被占用则递增。"""
    for port in range(preferred, preferred + 20):
        try:
            with socketserver.TCPServer(("127.0.0.1", port), AuditHandler) as s:
                s.server_close()
                return port
        except OSError:
            continue
    return preferred


def main():
    parser = argparse.ArgumentParser(description="智能审计可视化平台启动器")
    parser.add_argument("--port", type=int, default=8765, help="服务器端口 (默认 8765)")
    parser.add_argument("--regen", action="store_true", help="重新运行审计生成数据")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    # 检查 web 目录
    if not (WEB_DIR / "index.html").exists():
        print(f"错误: 找不到 web 界面文件 {WEB_DIR / 'index.html'}")
        return

    # 确保数据
    if not ensure_data(regen=args.regen):
        print("无法获取审计数据，请先运行: python demo/run_audit_report.py")
        return

    # 找可用端口
    port = find_free_port(args.port)
    if port != args.port:
        print(f"端口 {args.port} 被占用，改用 {port}")

    url = f"http://127.0.0.1:{port}"

    print("=" * 50)
    print("  智能审计可视化平台")
    print("=" * 50)
    print(f"  地址: {url}")
    print(f"  数据: {DATA_PATH}")
    print(f"  Web:  {WEB_DIR}")
    print("=" * 50)
    print("  按 Ctrl+C 停止服务器")
    print()

    # 延迟打开浏览器
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    # 启动服务器
    with socketserver.TCPServer(("127.0.0.1", port), AuditHandler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n服务器已停止")
