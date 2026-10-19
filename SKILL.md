---
name: aliyun-sls-query
description: 直接查询阿里云 SLS 日志服务（Log Service）——查 project/logstore 列表、拉取指定时间窗口日志、统计接口请求分布与错误。当用户提到 SLS / 阿里云日志 / k8s-log-<project> project / 某个容器(如 <module>-backend)的日志 / "查一下日志" / 报货单等 save 类保存接口的改动记录与汇总 HTML 汇报 时使用。无需安装 SDK，纯 Python 标准库签名调用。
agent_created: true
---

# 阿里云 SLS 日志查询

## 1. 拿凭据（脚本已脱敏，无需改代码）

所有脚本通过 `scripts/sls_auth.py` 的 `load_credentials()` 自动解析 AK/SK，优先级：

1. 环境变量 `ALIBABA_CLOUD_ACCESS_KEY_ID` / `ALIBABA_CLOUD_ACCESS_KEY_SECRET`（**推荐**，CI / 多账号切换最干净）。
2. `~/.workbuddy/mcp.json` 里 `mcpServers.alibabacloud-sls.env.*`（本机已带，日常本地使用零配置即可）。
3. `~/.aliyun/config.json`（aliyun CLI 的 profile）。

脚本文件内**不再硬编码任何密钥**，可安全提交 / 发布到公开仓库。
**换 AK/SK 只需改上面任一来源**，无需动脚本；若全部缺失，脚本会抛出可读的报错提示如何配置。

### 可选环境变量（配置项，非密，均带默认值）

- `SLS_PROJECT` —— 默认读 `scripts/sls_defaults.local.json`（占位 `k8s-log-<project-id>`；公开仓库不含此文件，克隆后需自行指定或自建本地文件）
- `SLS_ENDPOINT` —— 默认 `cn-hangzhou.log.aliyuncs.com`（占位 `cn-<region>.log.aliyuncs.com`）
- `SLS_LOGSTORE` —— 默认读 `scripts/sls_defaults.local.json`（占位 `<module>-backend`）

改查询目标时也可直接编辑对应脚本顶部的同名常量。

## 1.5 已知可访问的 SLS 项目（环境）

本 AK 可访问其权限范围内的**任意** project / logstore（同一组 AK/SK，靠 `SLS_PROJECT` / `SLS_LOGSTORE` 环境变量切换；`sls_probe.py` 也可用 `SLS_PROJECT=xxx` 覆盖后逐个 region 试探）。项目命名通常为 `k8s-log-<hash>`，模块类 logstore 形如 `<module>-backend`（如 `inc-backend` / `acc-backend` / `interface-backend` 等）。

以下仅为**示例**，实际以你的 AK 权限为准（默认值来自本机 `scripts/sls_defaults.local.json`，不随仓库发布，故公开仓库里看不到具体 project 名）：

| 说明 | PROJECT | LOGSTORE | ENDPOINT | 备注 |
|---|---|---|---|---|
| 示例·测试 | `k8s-log-<project-id>` | `<module>-backend` | `cn-hangzhou.log.aliyuncs.com` | 占位示例 |
| 示例·生产 | `k8s-log-<project-id>` | `<module>-backend` | `cn-hangzhou.log.aliyuncs.com` | 占位示例 |

> 切换示例：`SLS_PROJECT=k8s-log-xxxx SLS_LOGSTORE=acc-backend python sls_search.py ...`
> region 通常是 `cn-hangzhou`（或你账号所在 region），仅 project/logstore 名不同。

## 2. 确定 region（最容易卡住的一步）

project 名本身不含 region。用 `scripts/sls_probe.py` 对候选 endpoint 逐个请求 `GET http://<project>.<region>.log.aliyuncs.com/`：

```bash
cd <workspace> && python sls_probe.py
```

返回 200 即为命中，同时打印 project 描述等元信息；随后自动列出该 project 全部 logstore。
脚本已内置 30+ region 候选，首个命中即停。**已知常用：cn-hangzhou。**

## 3. 拉日志与统计

- `scripts/sls_query.py` —— 签名 + `GetLogs` 封装（支持 SQL 模式）。
- `scripts/sls_analyze.py` —— 分页拉取时间窗全部日志，本地正则解析，输出：级别分布、URI TOP（含数字/UUID 折叠归一化）、Controller.method TOP、耗时统计、Pod 分布、ERROR 明细、非请求类日志归类。

```bash
python sls_analyze.py 15   # 近 15 分钟，参数可改 30/60
```

改查询目标用环境变量 `SLS_PROJECT` / `SLS_LOGSTORE` / `SLS_ENDPOINT`，或在本机 `scripts/sls_defaults.local.json` 里指定默认目标（该文件 gitignore，不提交）。

## 4. 两个必知坑

**坑 A：正文字段通常没开索引，SQL 聚合会失败。**
报错 `Column 'content' cannot be resolved; please add the column in the index attribute` 就说明该 logstore 只对部分字段建了索引，**不要试图用 SQL 分析日志正文**，改用「全量拉取 + 本地正则统计」。若要用 SQL，先确认字段已加入索引。

**坑 B：签名与 URL 编码不一致会 401 SignatureNotMatch。**
- 签名串里 query 参数必须用**未 URL 编码**的原始值（`query=* | select ...`）；
- 发送的 URL 只编码 value，保留 `key=value` 结构。用 `urllib.parse.urlencode(pairs, quote_via=urllib.parse.quote)`，直接对 `"from=123"` 整体 `quote(safe="")` 会把 `=` 编码成 `%3D` 导致签名失败。
- 必需请求头：`Date`(GMT) / `Content-Type` / `x-log-apiversion: 0.6.0` / `x-log-signaturemethod: hmac-sha1` / `x-log-bodyrawsize: 0` / `Host`。
- 签名串 = `VERB\nMD5\nContent-Type\nDate\n` + 排序后的 `x-log-*`/`x-acs-*` 头（`key:value\n`）+ `uri?sorted_params`；`Authorization: LOG <ak>:<base64(hmac-sha1)>`

## 4.5 按 traceId 追踪整条链路（查"某个请求执行了什么 SQL"的标准做法）

`scripts/sls_trace.py` 已封装：先用关键词（URI 名 / storeCode 等）捞请求日志 → 提取 traceId → 再用 traceId 捞该链路全部日志（含 MyBatis SQL）。

```bash
python sls_trace.py 24 <门店号>     # 近 24 小时；门店号必填，裸号会自动补 1_ 前缀
```

日志格式为 `[traceId spanId]`，例：`[d2e2f16306adaf84 d2e2f16306adaf84]`。同一 traceId 下跨线程（XNIO-1 task-N、openStoreExecutorN）的日志都能串起来。

MyBatis DEBUG 三件套（都在 `content` 里，可全文检索）：
- `xxxMapper方法名: ==>  Preparing: <带 ? 的 SQL>`
- `xxxMapper方法名: ==> Parameters: 值1(类型), 值2(类型), ...`
- `xxxMapper方法名: <==      Total: N`（SELECT 返回行数）/ `<==    Updates: N`（写操作影响行数）

**坑 C：请求参数里的 storeCode 与 DB 里的 store_code 可能不一致。**
例：`/inc/dataCenter/syncStoreEstQuantity` 请求体里是 `"storeCode":"<门店号>"`，但落库 SQL 参数是 `1_<门店号>`（**业务前缀 `1_`**），unique_del_flag 也拼成 `<门店号>_<日期>_<物料码>`。**按门店查 SQL 时必须带上 `1_` 前缀（如 `1_<门店号>`），不要只搜请求体里的裸门店号。**

**坑 D：整批 INSERT 会淹没链路日志。** 一次 syncStoreEstQuantity 可能有 500+ 条日志（几十条 `insert ==> Parameters`），看链路时先用 `sls_chain.py` 压成摘要行，再用 `sls_merch.py` 按关键 CODE 精确定位。

### 配套脚本
- `sls_chain.py <traceId> [hours]` —— 把整条链路压成 `PREPARE / PARAMS / RESULT(Total|Updates) / ASPECT` 摘要行，快速看清做了哪些 SQL。
- `sls_merch.py <物料码> [hours] [traceId,...]` —— 按业务主键（物料码/订单号）定位命中位置，**并自动带上紧随其后的 `<== Total/Updates` 行**（结果行本身不含业务主键，必须带上才知道执行是否成功）。
- `sls_window.py "YYYY-MM-DD HH:MM:SS" "YYYY-MM-DD HH:MM:SS"` —— 秒级时间窗全量拉取，用于观察某次定时任务/异常时刻的完整上下文。
- `sls_order.py <订单号> [hours]` —— 由新到旧看某个单号的状态流转。
- `sls_savecompare.py <logstore> <keyword> <hours> [max_lines]` —— **save 类接口的"参数变更比对"通用工具**，自动处理坑 F/G/H：按 URI 里的 `/app/` 自动区分 PC/APP 端点、按「整单快照=整体替换 / 增量=按业务主键更新」做状态叠加、自动提取行尾操作人(工号)。把 `keyword` 直接拼上订单号（如 `"saveOrderQuantity <订单号>"`）可只拉目标单。关键参数：`--list-key`(物料列表字段,默认 merchandiseListSaveList) / `--item-key`(业务主键,默认 merchandiseCode) / `--owner-key`+`--owner-value`(按订单号过滤) / `--qty-keys`(比对的数量字段,逗号分隔) / `--del-key`(删除列表字段) / `--cache <raw.json>`(跳过 SLS 复用落盘数据)。产出 `savecompare_report.md` + `savecompare_changes.csv`(逐次改动长表: 步骤/时间/端点/操作人/改动类型/物料/前后值) + `savecompare_final_vs_initial.csv`(全量初始↔最终)。
- `sls_savecompare_html.py --order <报货单号> --store <门店storeCode> [--src <数据来源>] [--window <时间窗>] [--indir <产物目录>] [--out <文件名>]` —— **把上一条的产物转成自包含汇总 HTML**（可直接分享/发布）。产出结构固定：概览卡（保存次数/PC+APP/操作人/物料初始→最终/新增/净变更）→ 操作人视角 → 完整改动流水（按时间升序，每步带端点/操作人/整单或增量/逐条物料变化）→ 变动点速览（新增/删除/减量/增量Top8）→ 订货量净变更全表。样式为统一的「报货单改动流水汇报」标准样式，**生成结果可直接对外分享**。

**坑 E：定时任务日志没有 traceId。** xxl-job 打出来的是 `[ ] [ Thread-44]`（方括号内为空），只能靠**秒级时间窗**或接口名去定位，别指望 traceId 串联。找"某张表为什么被改了"时，`sls_window.py` 比 trace 追踪更快。

**坑 F：同一接口存在 PC 端与 APP 端两套 URI，全文检索会一并命中。** 报货/ routine 类接口常有 `/inc/routineOrder/saveOrderQuantity`（PC）和 `/inc/**app**/routineOrder/saveOrderQuantity`（APP）两个端点。用关键字 `saveOrderQuantity` 检索时**两者都会命中**，极易把 APP 操作误并入 PC 统计。正确做法：拉到全量后，用每行 `RUI = [<uri>]` 里的 `/app/` 子串做**端点分类**（PC=不含 `/app/`、APP=含 `/app/`），而不是靠 URI 关键字区分。`sls_search.py` 已自动打印 `endpoint=PC/APP`。

**坑 G：增量保存接口不能直接做"两次相减"，要用状态叠加模型重建。** 像 `saveOrderQuantity` 这类保存接口，单次请求可能只带**被改动的单行**（且携带的是新绝对值，不是增量），也可能**整单重存**。因此：
- 不能在相邻两次保存间做"差异减法"得出改动；
- 应维护一个共享状态：整单快照 = 整体替换，增量保存 = 按业务主键（如物料码 `merchandiseCode` + `orderCode`）更新对应行；
- 逐次叠加出每个时刻的真实状态，再对比首末态得到净变更。
报货单参数通用结构（供解析参考）：`arg0.merchandiseListSaveList[]` 每项含 `orderCode` / `merchandiseCode` / `merchandiseName` / `orderQuantity`(订货量) / `adjustQuantity`(调整量)，`arg0.delMerchandiseCodeList` 为删除的物料码；一次保存若混合多订单，必须按 `orderCode` 过滤出目标单后再比对。

**坑 H：操作人（工号）只在日志行末尾，脚本默认不提取。** 业务请求成功行格式为 `...} 操作人 = <工号> IP = <ip>`，`result = {...}` 之后、行尾。参数体和 traceId 里**都没有**操作人，必须用正则 `操作人\s*=\s*(\S+)` 从 `content` 末尾捞。注意日志只记录工号，没有姓名。`sls_search.py` / `sls_analyze.py` 已默认统计操作人分布。

## 4.6 报货单改动 → 汇总 HTML（意图驱动）

用户查询**报货单 / save 类保存接口的改动记录**时，按意图分两档决定是否收尾生成汇总 HTML：

| 用户意图 | 该怎么收尾 |
|---|---|
| **交付型**：含「汇报 / 汇总 / 完整流水 / 变动点 / 分享 / 给别人看 / 在线看 / 改动报告」等表述 | **直接生成 HTML 收尾**，不必先问。产出后再主动问一句是否需要发布为在线链接。 |
| **快速事实型**：只问某个点，如「谁改的 / 改了几次 / 某个物料改了多少 / 最后一次是谁改的」 | **直接给答案**，末尾附一句「需要的话我可以生成同样的汇总 HTML」。不要为了生成而生成。 |

理由：交付型需求漏掉 HTML 会导致用户必须再追问一次（历史上一再发生）；快速查询场景下生成 HTML 是纯浪费。所以**不要**不管什么意图都固定弹一句"要不要生成 HTML"，也**不要**因为用户没明说 HTML 就完全不做。

标准两步流程：

```
# 1) 拉数据 + 状态叠加比对（PC/APP 自动分离、操作人工号自动提取）
SLS_PROJECT=... SLS_LOGSTORE=... \
python sls_savecompare.py <module>-backend \
    "saveOrderQuantity <订单号>" 40 \
    --owner-key orderCode --owner-value <订单号> --out-dir out

# 2) 生成汇报 HTML（样式统一）
python sls_savecompare_html.py \
    --order <订单号> --store <门店storeCode> \
    --src "<module>-backend（阿里云 SLS）" \
    --window "YYYY-MM-DD HH:MM:SS ~ YYYY-MM-DD HH:MM:SS" \
    --indir out --out save_order_report.html
```

要点：
- 第 2 步**只依赖**第 1 步的 `savecompare_raw.json` + `savecompare_final_vs_initial.csv`，可反复重跑生成 HTML，不必重复打 SLS 接口。
- HTML 的时间线是从 `raw.json` **重放状态叠加**重建的（**不要**直接读 `changes.csv`），因为 `changes.csv` 的端点/分步判定有 bug 会算错。
- `--qty-key` 默认 `orderQuantity`，对应 `final_vs_initial.csv` 的 `init_/final_/delta_orderQuantity` 列；若比对时改了 `--qty-keys`，这里要同步传 `--qty-key`。
- 运行时会把口径数字打印到终端（`操作步/PC/APP/初始→最终/新增/删除/净变更/增量/减量`），**先核对再交付**。
- 若用户要点在线链接：`workbuddy_sites_deploy` 是**单站点**模式，多个报货单要**合并进同一目录一次性部署**（各报告放同目录 + 一个汇总 index.html），否则后部署会覆盖先部署的链接。

## 5. 结果解读要点

- ACK 容器日志的容器名在 `__tag__:_container_name_`，Pod 在 `__tag__:_pod_name_`，正文在 `content`。
- 操作人（工号）在业务请求行**末尾**：`result = {...} 操作人 = <工号> IP = <ip>`，用 `操作人\s*=\s*(\S+)` 提取；参数体里没有工号，日志只记录工号不记录姓名。
- Java 服务常见请求行格式：`LogAspect: [xxx]-[Controller.method] RUI = [/path] 耗时 = [N]` → 用 `RUI = \[([^\]]*)\]` 提取 URI、`耗时 = \[(\d+)\]` 提取耗时。
- HikariPool 的 add/close/cleanup 日志量大属正常，统计请求时应排除（脚本已按「是否含 RUI」区分业务请求与框架日志）。
- 健康检查（actuator/health）占比高是常态，汇报时应单独说明，别和业务请求混算。
