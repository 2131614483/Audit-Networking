# [CO-05] 定制指南

填充顺序（L0→L4，参见预制菜规范 §5.2）：

1. **L1 配置**：改 `config/custom.yaml`（阈值、连接地址），不改代码。
2. **L2 规则/阈值/格式**：改 `src/custom/custom_{rules,thresholds,formatter}.py`，无需动 engine。
3. **L3 核心算法**：改 `src/engine.py`，填充 `# TODO[kg_gnn]: ...` 标记的方法。
4. **L4 接口/管道**：改 `src/api.py` / `src/pipeline.py`，调整端点与流程编排。

扩展点清单：
- `src/custom/custom_rules.py` → `apply_custom_rules(result, config)`
- `src/custom/custom_thresholds.py` → `apply_thresholds(result, config)`
- `src/custom/custom_formatter.py` → `format_output(result)`
- `src/engine.py` → `_load_model / _preprocess / _infer / _postprocess`
