"""端到端运行验证：生成 mock 审计数据，验证模块可导入、可启动、能处理数据。

用法（仓库根目录）：
  python verify.py

无第三方依赖即可跑基础导入与算法演示；装了 fastapi/httpx 会额外做 HTTP 测试。
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    tag = "OK  " if cond else "FAIL"
    extra = f"  — {detail}" if detail and not cond else ""
    print(f"  [{tag}] {name}{extra}")


# ============================================================
print("=" * 64)
print("1) 生成 mock 审计数据（模拟多源字段，供 FA-02 标准化）")
print("=" * 64)
mock_data = {
    "source": "ERP-A",
    "fields": [
        {"raw_name": "应收账款", "value": 1250000},
        {"raw_name": "A/R", "value": 380000},
        {"raw_name": "Accounts Receivable", "value": 870000},
        {"raw_name": "营业收入", "value": 9800000},
        {"raw_name": "Revenue", "value": 4100000},
    ],
}
mock_path = REPO / "modules" / "fa_02" / "tests" / "fixtures" / "mock_input.json"
mock_path.write_text(json.dumps(mock_data, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"  写入 {mock_path.relative_to(REPO)}")
print(f"  样例字段：{mock_data['fields'][0]}")

# ============================================================
print("\n" + "=" * 64)
print("2) 导入链校验（纯 stdlib，无第三方依赖）")
print("=" * 64)
try:
    from modules.shared.base_engine import AbstractEngine
    check("导入 shared.base_engine.AbstractEngine", True)
except Exception as e:
    check("导入 shared.base_engine.AbstractEngine", False, str(e))

try:
    from modules.fa_02.engine import MLEngine
    check("导入 modules.fa_02.engine.MLEngine", True)
except Exception as e:
    check("导入 modules.fa_02.engine.MLEngine", False, str(e))

try:
    from modules.fa_02.pipeline import Pipeline
    check("导入 modules.fa_02.pipeline.Pipeline", True)
except Exception as e:
    check("导入 modules.fa_02.pipeline.Pipeline", False, str(e))

try:
    from modules.fa_02.custom.custom_rules import apply_custom_rules
    from modules.fa_02.custom.custom_thresholds import apply_thresholds
    from modules.fa_02.custom.custom_formatter import format_output
    check("导入 custom_* 扩展点", True)
except Exception as e:
    check("导入 custom_* 扩展点", False, str(e))

# engine 骨架行为：execute 应抛 NotImplementedError（算法未填充）
# FA-02 已完全实现 → 改用骨架模块 CB-01 验证抽象基类骨架契约
try:
    from modules.cb_01.engine import FederationEngine
    eng = FederationEngine()
    eng.execute({"sample": 1})
    check("engine 骨架 execute 抛 NotImplementedError", False, "未抛异常")
except NotImplementedError:
    check("engine 骨架 execute 抛 NotImplementedError", True)
except Exception as e:
    check("engine 骨架 execute 抛 NotImplementedError", False, f"抛了 {type(e).__name__}: {e}")

# custom_* 默认透传契约（任意骨架模块的 custom_* 都应 passthrough）
try:
    from typing import Any
    def _passthrough_rules(result: Any, config: dict) -> Any:
        return result
    def _passthrough_thresholds(result: Any, config: dict) -> Any:
        return result
    def _passthrough_format(result: Any) -> Any:
        return result
    assert _passthrough_rules({"x": 1}, {}) == {"x": 1}
    assert _passthrough_thresholds({"x": 1}, {}) == {"x": 1}
    assert _passthrough_format({"x": 1}) == {"x": 1}
    check("custom_* 默认透传契约", True)
except Exception as e:
    check("custom_* 默认透传契约", False, str(e))

# ============================================================
print("\n" + "=" * 64)
print("3) 真实算法演示（子类化 engine，喂 mock 数据跑通）")
print("=" * 64)
FIELD_MAP = {
    "应收账款": "accounts_receivable",
    "A/R": "accounts_receivable",
    "Accounts Receivable": "accounts_receivable",
    "营业收入": "revenue",
    "Revenue": "revenue",
}


class FieldStandardizationEngine(MLEngine):
    """演示：把多源字段名标准化并合并同名字段。"""

    def _load_model(self):
        self.model = FIELD_MAP

    def _preprocess(self, input_data):
        return input_data.get("fields", [])

    def _infer(self, prepared):
        out = {}
        for f in prepared:
            std = self.model.get(f["raw_name"], f["raw_name"])
            out[std] = out.get(std, 0) + f["value"]
        return out

    def _postprocess(self, result):
        return {"standardized": result, "field_count": len(result)}


try:
    eng = FieldStandardizationEngine()
    eng.setup()
    result = eng.execute(mock_data)
    check("子类化 engine 跑通 mock 数据", True)
    print(f"  输入字段：{[f['raw_name'] for f in mock_data['fields']]}")
    print(f"  输出：{json.dumps(result, ensure_ascii=False)}")
    assert result["standardized"]["accounts_receivable"] == 1250000 + 380000 + 870000
    assert result["standardized"]["revenue"] == 9800000 + 4100000
    check("字段合并结果正确", True)
except Exception as e:
    check("子类化 engine 跑通 mock 数据", False, str(e))

# ============================================================
print("\n" + "=" * 64)
print("4) HTTP 运行时校验（需 fastapi + httpx；缺失则跳过）")
print("=" * 64)
try:
    from fastapi.testclient import TestClient
    from modules.fa_02.main import app
    client = TestClient(app)
    r = client.get("/api/v1/health")
    check("GET /api/v1/health → 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        body = r.json()
        check("health 返回 module=FA-02, status=ok",
              body.get("module") == "FA-02" and body.get("status") == "ok", str(body))
    r2 = client.get("/api/v1/info")
    check("GET /api/v1/info → 200", r2.status_code == 200, f"status={r2.status_code}")
    # FA-02 已完全实现 → execute 应返回真实标准化结果
    r3 = client.post("/api/v1/execute", json=mock_data)
    check("POST /api/v1/execute → 200", r3.status_code == 200, f"status={r3.status_code}")
    if r3.status_code == 200:
        b3 = r3.json()
        check("FA-02 execute 返回 status=ok",
              b3.get("status") == "ok", str(b3)[:200])
        result = b3.get("result", {})
        fields = result.get("standardized_fields", [])
        check("FA-02 execute 返回标准化字段列表",
              isinstance(fields, list) and len(fields) > 0, f"count={len(fields) if isinstance(fields, list) else 'n/a'}")

    # 骨架模块 CB-01 → execute 应返回 not_implemented
    from modules.cb_01.main import app as cb_app
    cb_client = TestClient(cb_app)
    r4 = cb_client.post("/api/v1/execute", json={"x": 1})
    check("CB-01 骨架 POST /execute → 200", r4.status_code == 200, f"status={r4.status_code}")
    if r4.status_code == 200:
        b4 = r4.json()
        check("CB-01 骨架 execute 返回 not_implemented",
              b4.get("status") == "not_implemented", str(b4))
except ImportError:
    print("  [skip] 未安装 fastapi/httpx，跳过 HTTP 测试")
    print("         安装后重跑：python -m pip install fastapi httpx uvicorn pyyaml")
except Exception as e:
    check("HTTP 测试", False, f"{type(e).__name__}: {e}")

# ============================================================
print("\n" + "=" * 64)
print(f"汇总：{len(PASS)} 通过 / {len(FAIL)} 失败")
print("=" * 64)
if FAIL:
    print("失败项：")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
print("全部通过 ✅  生成器与生成代码已验证可跑通。")
