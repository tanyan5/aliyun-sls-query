# aliyun-sls-query

WorkBuddy / Agent 技能：直接查询阿里云 SLS 日志服务（无需安装 SDK，纯 Python + 签名），覆盖 inc-backend（UAT/测试）与 inc-backend-pro（生产）等项目的日志检索、traceId 串联、ERROR 统计，以及对 save 类接口做「状态叠加」参数比对。

## 功能

- 项目 / region 自动探测（`sls_probe.py`）
- 关键字检索、时间窗查询，支持升序 / 降序（`sls_search.py`、`sls_query.py`）
- traceId 串联、Pod / 容器维度统计（`sls_trace.py`、`sls_traceid.py`、`sls_chain.py`、`sls_analyze.py`）
- **`sls_savecompare.py`**：对任意 save 类接口，自动按「整单快照 = 整体替换 / 增量 = 按业务主键更新」做状态叠加重建，并从日志行尾提取**操作人工号**与 **PC/APP 端点**，输出「逐次改动长表」与「初始↔最终净变更全表」。已沉淀的坑：PC/APP 双端 URI 易混淆、增量保存不能两次相减、操作人只在行尾。

## 用法

详见 `SKILL.md`（含环境常量、region 探测、常见坑位说明）。

## 已知环境

| 环境 | PROJECT | LOGSTORE |
|---|---|---|
| UAT / 测试 | `k8s-log-c690075cfa6764ccda7b33582e001db23` | `inc-backend` |
| 生产 | `k8s-log-c059c76add58a445da01534a603995df4` | `inc-backend-pro` |

> 切换方式：`SLS_PROJECT=... SLS_LOGSTORE=... python sls_search.py ...`
