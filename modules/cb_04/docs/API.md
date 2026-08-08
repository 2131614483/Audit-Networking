# [CB-04] API 说明

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/v1/health | 健康检查 |
| GET | /api/v1/info | 模块信息 |
| POST | /api/v1/execute | 触发执行（算法未填充时返回 not_implemented） |

启动：`python -m modules.cb_04.main`（端口 9004）
