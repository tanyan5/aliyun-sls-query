# aliyun-sls-query

WorkBuddy / Agent 技能：直接查询阿里云 SLS 日志服务（无需安装 SDK，纯 Python + 签名），覆盖任意 `<module>-backend` 等项目（如 inc-backend / acc-backend / interface-backend）的日志检索、traceId 串联、ERROR 统计，以及对 save 类接口做「状态叠加」参数比对；project / logstore 通过环境变量切换，可查 AK 权限内的任意目标。

## 首次使用（需要配两样东西）

克隆后默认值都是**占位符**，必须先配好下面两项才能查日志（脚本内不含任何密钥或具体 project 名）。

### ① AK/SK（身份）

任选其一，优先级从高到低：

```bash
# 推荐：环境变量
export ALIBABA_CLOUD_ACCESS_KEY_ID=<你的 AccessKeyId>
export ALIBABA_CLOUD_ACCESS_KEY_SECRET=<你的 AccessKeySecret>
```
- 或写进 `~/.workbuddy/mcp.json` 的 `mcpServers.alibabacloud-sls.env.*`
- 或使用 `aliyun` CLI 的 `~/.aliyun/config.json`

### ② 查询目标（project / logstore）

```bash
export SLS_PROJECT=k8s-log-xxxxxxxxxxxxxxxx          # 日志项目名（形如 k8s-log-<hash>）
export SLS_LOGSTORE=<module>-backend                 # 如 inc-backend / acc-backend
export SLS_ENDPOINT=cn-hangzhou.log.aliyuncs.com     # 可选，默认杭州
```

或在本目录 `scripts/sls_defaults.local.json` 里写（该文件已被 gitignore，不会提交）：

```json
{"project":"k8s-log-xxxxxxxx","logstore":"<module>-backend","endpoint":"cn-hangzhou.log.aliyuncs.com"}
```

> 不知道 project 名？先设 `SLS_PROJECT`，再跑 `python scripts/sls_probe.py` 探测可访问的 region 与 logstore 列表。

### 验证

```bash
python scripts/sls_query.py     # 应返回 code=200 与近 15 分钟日志
```

> 两项任一未配置时，脚本会**直接给出明确的配置指引**（不会静默返回「命中 0 条」让你误以为没日志）。

## 功能

- 项目 / region 自动探测（`sls_probe.py`）
- 关键字检索、时间窗查询，支持升序 / 降序（`sls_search.py`、`sls_query.py`）
- traceId 串联、Pod / 容器维度统计（`sls_trace.py`、`sls_traceid.py`、`sls_chain.py`、`sls_analyze.py`）
- **`sls_savecompare.py`**：对任意 save 类接口，自动按「整单快照 = 整体替换 / 增量 = 按业务主键更新」做状态叠加重建，并从日志行尾提取**操作人工号**与 **PC/APP 端点**，输出「逐次改动长表」与「初始↔最终净变更全表」。已沉淀的坑：PC/APP 双端 URI 易混淆、增量保存不能两次相减、操作人只在行尾。
- **`sls_savecompare_html.py`**：把上一条的产物转成**自包含汇总 HTML**（可直接分享 / 发布）。产出：概览卡 → 操作人视角 → 完整改动流水（按时间升序）→ 变动点速览 → 订货量净变更全表，样式统一。

## 用法

详见 `SKILL.md`（含环境常量、region 探测、常见坑位说明，以及「报货单改动 → 汇总 HTML」的标准收尾流程）。

报货单改动出汇总 HTML 的两步：

```bash
# 1) 拉数据 + 状态叠加比对
python sls_savecompare.py <module>-backend "saveOrderQuantity <订单号>" 40 \
    --owner-key orderCode --owner-value <订单号> --out-dir out

# 2) 生成汇报 HTML
python sls_savecompare_html.py --order <订单号> --store <门店storeCode> \
    --src "<module>-backend（阿里云 SLS）" \
    --window "YYYY-MM-DD HH:MM:SS ~ YYYY-MM-DD HH:MM:SS" \
    --indir out --out save_order_report.html
```

## 可访问的 SLS 项目（示例，非穷举）

本 AK 可访问其权限范围内的**任意** project / logstore，靠环境变量 `SLS_PROJECT` / `SLS_LOGSTORE` / `SLS_ENDPOINT` 切换；默认值来自本机 `scripts/sls_defaults.local.json`（gitignore，不随仓库发布）。项目命名通常为 `k8s-log-<hash>`，模块类 logstore 形如 `<module>-backend`（如 `inc-backend` / `acc-backend` / `interface-backend` 等）。

| 说明 | PROJECT | LOGSTORE |
|---|---|---|
| 示例·测试 | `k8s-log-<project-id>` | `<module>-backend` |
| 示例·生产 | `k8s-log-<project-id>` | `<module>-backend` |

> 切换方式：`SLS_PROJECT=k8s-log-xxxx SLS_LOGSTORE=acc-backend python sls_search.py ...`
