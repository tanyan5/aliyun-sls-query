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
import pathlib


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
