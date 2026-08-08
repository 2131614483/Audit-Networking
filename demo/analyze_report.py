"""分析模块测试报告。"""
import json
from pathlib import Path

r = json.loads((Path(__file__).parent / "module_test_report.json").read_text(encoding="utf-8"))
p = sum(1 for x in r if x["status"] == "pass")
f = sum(1 for x in r if x["status"] == "fail")
w = sum(1 for x in r if x["status"] == "warn")
print(f"通过{p} 失败{f} 警告{w} 总{len(r)}")
print(f"\n--- 失败({f}) ---")
for x in r:
    if x["status"] == "fail":
        print(f"  {x['slug']}: {x['error'][:90]}")
print(f"\n--- 警告({w}) ---")
for x in r:
    if x["status"] == "warn":
        print(f"  {x['slug']}: {x['error'][:90]}")
