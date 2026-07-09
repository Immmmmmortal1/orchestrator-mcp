from __future__ import annotations

"""Web UI 与 API 用的中文标签、说明文案（集中维护）。"""

SOURCE_LABELS_ZH: dict[str, str] = {
    "env": "环境变量",
    "local": "WebUI 本地",
    "server_md": "服务器.md",
    "none": "未配置",
}

PROVIDER_LABELS_ZH: dict[str, dict[str, str]] = {
    "deepseek": {
        "label_zh": "DeepSeek",
        "vendor_zh": "深度求索",
        "description_zh": "OpenAI 兼容 API；适合长文本审查或低成本 reviewer。",
    },
    "moonshot": {
        "label_zh": "Moonshot",
        "vendor_zh": "月之暗面 · Kimi",
        "description_zh": "Kimi 系列；适合长上下文审查与总结。",
    },
    "zhipu": {
        "label_zh": "智谱 GLM",
        "vendor_zh": "智谱 AI",
        "description_zh": "别名 glm；可作为快速审查模型。",
    },
    "openai": {
        "label_zh": "OpenAI",
        "vendor_zh": "OpenAI / GPT",
        "description_zh": "官方 Chat Completions；若走 Codex 中转请改用 codex-lb 或设 wire_api=responses。",
    },
    "codex-lb": {
        "label_zh": "Codex 中转",
        "vendor_zh": "codex-lb · Responses API",
        "description_zh": "对应 Codex CLI 的 wire_api=responses；Base URL 形如 …/backend-api/codex，走 /responses（SSE）。",
    },
    "stub": {
        "label_zh": "Stub 离线",
        "vendor_zh": "内置占位",
        "description_zh": "不调真实 API，仅用于自测 pipeline。",
    },
}

STAGE_LABELS_ZH: dict[str, dict[str, str]] = {
    "plan": {
        "label_zh": "规划 Plan",
        "description_zh": "拆任务、验收标准、风险；产出 plan.v1。",
    },
    "code": {
        "label_zh": "编码 Code",
        "description_zh": "按规划生成改动说明；产出 code_handoff.v1（不直接改仓库）。",
    },
    "review": {
        "label_zh": "审查 Review",
        "description_zh": "基于调用者提供的证据做 pass/revise 审查。",
    },
    "ui_review": {
        "label_zh": "UI 审查",
        "description_zh": "审查 Figma/截图/DebugBridge 证据，关注视觉还原、元素遗漏、交互与可访问性。",
    },
    "code_review": {
        "label_zh": "代码审查",
        "description_zh": "审查实现正确性、回归风险、架构、性能、安全与测试覆盖。",
    },
    "general_review": {
        "label_zh": "通用审查",
        "description_zh": "审查需求完整性、产品流程、边界场景与非 UI/代码专项问题。",
    },
    "deliver": {
        "label_zh": "交付 Deliver",
        "description_zh": "汇总结论、下一步与交付说明；产出 deliver.v1。",
    },
}

SCHEMA_LABELS_ZH: dict[str, str] = {
    "plan.v1": "规划 JSON 结构",
    "code_handoff.v1": "编码交接 JSON",
    "review.v1": "审查结果 JSON",
    "deliver.v1": "交付摘要 JSON",
}

PROFILE_LABELS_ZH: dict[str, dict[str, str]] = {
    "daily-dev-stub": {
        "label_zh": "离线自测",
        "description_zh": "三类审查角色均用 stub，不消耗 API；跑 verify / 联调 MCP 用。",
    },
    "daily-dev": {
        "label_zh": "日常开发",
        "description_zh": "UI / 代码 / 通用三类审查角色；provider/model 可在 WebUI Stages 中覆盖。",
    },
    "example-kimi-plan": {
        "label_zh": "多模型审查示例",
        "description_zh": "演示按 UI / 代码 / 通用审查角色分别选择模型。",
    },
}

FIELD_LABELS_ZH: dict[str, str] = {
    "api_key": "API 密钥",
    "base_url": "API 地址 (Base URL)",
    "default_model": "默认模型",
    "provider": "模型厂商",
    "model": "模型 ID",
    "schema": "交接 Schema",
    "profile": "编排方案 (Profile)",
}


def source_label_zh(source: str) -> str:
    return SOURCE_LABELS_ZH.get(source, source)


def provider_label_zh(provider: str) -> dict[str, str]:
    meta = PROVIDER_LABELS_ZH.get(provider, {})
    return {
        "label_zh": meta.get("label_zh", provider),
        "vendor_zh": meta.get("vendor_zh", ""),
        "description_zh": meta.get("description_zh", ""),
    }


def stage_label_zh(stage: str) -> dict[str, str]:
    meta = STAGE_LABELS_ZH.get(stage, {})
    return {
        "label_zh": meta.get("label_zh", stage),
        "description_zh": meta.get("description_zh", ""),
    }


def schema_label_zh(schema: str) -> str:
    return SCHEMA_LABELS_ZH.get(schema, schema)


def profile_label_zh(name: str, yaml_description: str = "") -> dict[str, str]:
    meta = PROFILE_LABELS_ZH.get(name, {})
    return {
        "label_zh": meta.get("label_zh", name),
        "description_zh": meta.get("description_zh", yaml_description),
    }
