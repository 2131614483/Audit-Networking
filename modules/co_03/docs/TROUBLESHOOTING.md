# 故障排查

| 现象 | 排查 |
|------|------|
| `ModuleNotFoundError: modules.shared` | 在仓库根目录运行，确保 cwd 在 path |
| `ModuleNotFoundError: fastapi` | 未建家族 venv，运行 `python modules/venvs/setup_venvs.py thin` |
| 端口冲突 | 见 module.yaml `runtime.port`，按业务域前缀分段 |
| `/execute` 返回 not_implemented | 正常，engine.py 算法未填充（TODO） |
| NotImplementedError | 填充对应 `# TODO[家族]:` 方法 |
