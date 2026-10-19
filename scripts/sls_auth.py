# -*- coding: utf-8 -*-
"""阿里云 AK/SK 解析（脚本内不存放任何密钥，便于公开发布）。

解析优先级：
  1. 环境变量 ALIBABA_CLOUD_ACCESS_KEY_ID / ALIBABA_CLOUD_ACCESS_KEY_SECRET
  2. ~/.workbuddy/mcp.json 中 mcpServers."alibabacloud-sls".env.*
  3. ~/.aliyun/config.json（aliyun CLI profile）
全部缺失则抛出可读的错误提示，告诉用户如何配置。
"""
import os
import json
import sys
import pathlib


def _install_clean_errors():
    """让配置类错误（RuntimeError）以友好文本输出，而不是整段 traceback。

    仅拦截 RuntimeError（本模块只用于 AK/SK 与查询目标两类配置报错），
    其他异常仍走默认 traceback，不影响调试。
    """
    def _hook(etype, value, tb):
        if issubclass(etype, RuntimeError):
            sys.stderr.write(str(value).rstrip() + "\n")
            sys.exit(1)
        sys.__excepthook__(etype, value, tb)
    sys.excepthook = _hook


_install_clean_errors()


def _load_json(path):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def load_credentials():
    """返回 (access_key_id, access_key_secret)。"""
    ak = (os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID") or "").strip()
    sk = (os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET") or "").strip()
    if ak and sk:
        return ak, sk

    # 回退 2：WorkBuddy 的 MCP 配置（本机已带 alibabacloud-sls 凭据）
    mcp = _load_json(pathlib.Path.home() / ".workbuddy" / "mcp.json")
    if mcp:
        env = (mcp.get("mcpServers", {})
                  .get("alibabacloud-sls", {})
                  .get("env", {}))
        ak = ak or (env.get("ALIBABA_CLOUD_ACCESS_KEY_ID") or "").strip()
        sk = sk or (env.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET") or "").strip()
        if ak and sk:
            return ak, sk

    # 回退 3：aliyun CLI 配置
    cfg = _load_json(pathlib.Path.home() / ".aliyun" / "config.json")
    if cfg:
        profs = cfg.get("profiles")
        prof = profs[0] if isinstance(profs, list) and profs else cfg
        ak = ak or (prof.get("access_key_id") or "").strip()
        sk = sk or (prof.get("access_key_secret") or "").strip()
        if ak and sk:
            return ak, sk

    raise RuntimeError(
        "未找到阿里云 AK/SK。请任选其一配置：\n"
        "  1) 设置环境变量 ALIBABA_CLOUD_ACCESS_KEY_ID / ALIBABA_CLOUD_ACCESS_KEY_SECRET\n"
        "  2) 在 ~/.workbuddy/mcp.json 的 mcpServers.alibabacloud-sls.env 中填入\n"
        "  3) 安装 aliyun CLI 并配置 ~/.aliyun/config.json"
    )


def require_target(project="", logstore="", endpoint=""):
    """校验查询目标是否仍是占位符；未配置时抛出清晰、可操作的报错。

    背景：脱敏后默认值是占位符（k8s-log-<project-id> / <module>-backend）。
    若新用户克隆仓库后未配置目标，请求会打到一个不存在的 project，
    表现为「HTTP 502 / 命中 0 条」——极易误判为"确实没有日志"。
    故在真正发起请求前先拦截，明确告诉用户该怎么配。

    参数传空串表示「这一项不需要校验」。
    """
    missing = []
    if project and "<project-id>" in project:
        missing.append("SLS_PROJECT")
    if logstore and "<module>" in logstore:
        missing.append("SLS_LOGSTORE")
    if endpoint and "<region>" in endpoint:
        missing.append("SLS_ENDPOINT")
    if not missing:
        return
    raise RuntimeError(
        "❌ SLS 查询目标尚未配置（%s 仍是占位符，当前 project=%r / logstore=%r）。\n"
        "   这不是「没有日志」，而是还没告诉脚本查询哪个 project / logstore。\n"
        "请任选一种方式配置后重试：\n"
        "   1) 环境变量（推荐）:\n"
        "        export SLS_PROJECT=k8s-log-xxxxxxxxxxxxxxxx\n"
        "        export SLS_LOGSTORE=<module>-backend        # 如 inc-backend / acc-backend\n"
        "        export SLS_ENDPOINT=cn-hangzhou.log.aliyuncs.com   # 可选，默认杭州\n"
        "   2) 在 scripts/ 目录下新建 sls_defaults.local.json:\n"
        "        {\"project\":\"k8s-log-xxxxxxxx\",\"logstore\":\"<module>-backend\",\"endpoint\":\"cn-hangzhou.log.aliyuncs.com\"}\n"
        "   3) 不确定 project 名时，先设 SLS_PROJECT 再跑 sls_probe.py 探测可访问的 region / logstore。\n"
        "   注：AK/SK 是另一项配置，见 load_credentials() 的报错提示。"
        % (
            "、".join(missing), project, logstore,
        )
    )


def load_defaults():
    """返回本机默认的 SLS 目标（project / logstore / endpoint）。

    来源：与本文件同目录、被 gitignore 的 `sls_defaults.local.json`
    （仅本机可用，不随仓库发布，故公开仓库不会泄露任何具体 project 名）。
    克隆仓库后若没有该文件，脚本会回退到占位符默认值，
    此时必须通过环境变量 SLS_PROJECT / SLS_LOGSTORE / SLS_ENDPOINT 指定目标。

    优先级：环境变量 > 本地 sls_defaults.local.json > 占位符。
    """
    p = pathlib.Path(__file__).resolve().parent / "sls_defaults.local.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}
