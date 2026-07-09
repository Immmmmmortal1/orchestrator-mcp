from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from orchestrator_mcp.config_store import (
    PROVIDER_IDS,
    add_custom_model,
    get_active_profile_name,
    get_profile_stages_for_ui,
    list_providers_for_ui,
    save_stage_overrides,
    set_active_profile_name,
    update_provider_from_ui,
)
from orchestrator_mcp.config import data_dir, package_root
from orchestrator_mcp.profiles import list_profiles

WEBUI_ROOT = Path(__file__).resolve().parent
STATIC_DIR = WEBUI_ROOT / "static"

MCP_TOOLS: list[dict[str, str]] = [
    {
        "name": "orchestrate_list_providers",
        "label_zh": "查看厂商配置",
        "desc_zh": "列出 deepseek / moonshot / zhipu / openai / codex-lb 是否已有密钥（不返回明文）。",
    },
    {
        "name": "orchestrate_provider_check",
        "label_zh": "检查单个厂商",
        "desc_zh": "检查指定 provider（含别名 glm、gpt、codex）是否已配置。",
    },
    {
        "name": "orchestrate_list_profiles",
        "label_zh": "列出编排方案",
        "desc_zh": "读取 profiles/*.yaml；返回 active_profile（WebUI 默认）与各方案 is_active。",
    },
    {
        "name": "orchestrate_effective_config",
        "label_zh": "查看有效配置",
        "desc_zh": "不调用模型，展示 UI / 代码 / 通用审查角色实际使用的 profile / provider / model / key 状态。",
    },
    {
        "name": "orchestrate_run_start",
        "label_zh": "创建编排任务",
        "desc_zh": "按 Profile 创建审查 run；可指定 ui_review / code_review / general_review。",
    },
    {
        "name": "orchestrate_dispatch",
        "label_zh": "执行单个 Stage",
        "desc_zh": "对 run_id 跑 ui_review / code_review / general_review 中的一步。",
    },
    {
        "name": "orchestrate_run_pipeline",
        "label_zh": "一键跑完整流水线",
        "desc_zh": "默认依次跑三类审查；传 stage 时只跑单个审查角色。",
    },
    {
        "name": "orchestrate_status",
        "label_zh": "查看任务状态",
        "desc_zh": "查询 run 进度、各 stage handoff 与 token 汇总。",
    },
    {
        "name": "orchestrate_handoff",
        "label_zh": "读取 Stage 产出",
        "desc_zh": "获取某 stage 最新 handoff JSON（plan.v1 等）。",
    },
    {
        "name": "orchestrate_stage_override",
        "label_zh": "运行时改 Stage",
        "desc_zh": "在 dispatch 前临时换某审查角色的 provider / model。",
    },
]

SHELL_COMMANDS: list[dict[str, str]] = [
    {
        "cmd": "cd orchestrator-mcp && ./start.sh",
        "desc_zh": "启动 MCP 服务（默认 http://127.0.0.1:18067/mcp）",
    },
    {
        "cmd": "cd orchestrator-mcp && ./start-webui.sh",
        "desc_zh": "启动本配置页（默认 http://127.0.0.1:18068）",
    },
    {
        "cmd": "cd orchestrator-mcp && ./verify.sh",
        "desc_zh": "离线自测 + WebUI API 冒烟",
    },
]

app = FastAPI(title="Orchestrator MCP Config", version="0.1.0")


class ProviderUpdate(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    default_model: str | None = None
    wire_api: str | None = None
    reasoning_effort: str | None = None
    clear_api_key: bool = False


class StageItem(BaseModel):
    provider: str
    model: str


class StagesUpdate(BaseModel):
    stages: dict[str, StageItem]
    set_as_default: bool = False
    active_profile: str | None = None  # legacy; prefer set_as_default


class ModelAdd(BaseModel):
    model: str = Field(min_length=1, max_length=128)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"ok": "true", "service": "orchestrator-webui"}


def _mcp_reachable(mcp_url: str) -> bool:
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(mcp_url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status < 500
    except urllib.error.HTTPError as exc:
        # MCP streamable-http 对裸 GET 常返回 406，说明进程在监听
        return exc.code in (200, 406)
    except OSError:
        return False


@app.get("/api/info")
def api_info() -> dict[str, object]:
    mcp_host = os.environ.get("ORCHESTRATOR_MCP_HOST", "127.0.0.1")
    mcp_port = os.environ.get("ORCHESTRATOR_MCP_PORT", "18067")
    webui_host = os.environ.get("ORCHESTRATOR_WEBUI_HOST", "127.0.0.1")
    webui_port = os.environ.get("ORCHESTRATOR_WEBUI_PORT", "18068")
    mcp_url = f"http://{mcp_host}:{mcp_port}/mcp"

    return {
        "service_id": "orchestrator-mcp",
        "service_name_zh": "多模型编排 MCP",
        "mcp_url": mcp_url,
        "webui_url": f"http://{webui_host}:{webui_port}",
        "mcp_reachable": _mcp_reachable(mcp_url),
        "package_root": str(package_root()),
        "data_dir": str(data_dir()),
        "cursor_mcp_config": {
            "mcpServers": {
                "orchestrator-mcp": {"url": mcp_url},
            }
        },
        "tools": MCP_TOOLS,
        "shell_commands": SHELL_COMMANDS,
        "notes_zh": [
            "WebUI 与 MCP 是同一目录下的两个进程：配置页 :18068，MCP :18067。",
            "改 WebUI 配置后无需重启 MCP；改环境变量后需重启 ./start.sh。",
            "复制 orchestrator-mcp 整个目录即可带走 WebUI 代码；data/*.local.json 为本机密钥与 Stage 覆盖（默认不进 git）。",
            "新机器需分别执行 ./start.sh 与 ./start-webui.sh，并在 Cursor 里配置 orchestrator-mcp。",
        ],
    }


@app.get("/api/providers")
def api_list_providers() -> dict[str, object]:
    return {"providers": list_providers_for_ui()}


@app.put("/api/providers/{provider}")
def api_update_provider(provider: str, body: ProviderUpdate) -> dict[str, object]:
    if provider not in PROVIDER_IDS:
        raise HTTPException(status_code=404, detail="unknown provider")
    try:
        row = update_provider_from_ui(
            provider,
            api_key=body.api_key,
            base_url=body.base_url,
            default_model=body.default_model,
            wire_api=body.wire_api,
            reasoning_effort=body.reasoning_effort,
            clear_api_key=body.clear_api_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "provider": row}


@app.post("/api/providers/{provider}/models")
def api_add_provider_model(provider: str, body: ModelAdd) -> dict[str, object]:
    if provider not in PROVIDER_IDS:
        raise HTTPException(status_code=404, detail="unknown provider")
    try:
        row = add_custom_model(provider, body.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "provider": row, "added_model": row.get("added_model")}


@app.get("/api/profiles")
def api_list_profiles() -> dict[str, object]:
    active = get_active_profile_name()
    return {
        "profiles": list_profiles(active_name=active),
        "active_profile": active,
    }


@app.get("/api/profiles/{profile_name}/stages")
def api_get_stages(profile_name: str) -> dict[str, object]:
    try:
        return get_profile_stages_for_ui(profile_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/api/profiles/{profile_name}/stages")
def api_save_stages(profile_name: str, body: StagesUpdate) -> dict[str, object]:
    payload = {
        stage: item.model_dump()
        for stage, item in body.stages.items()
    }
    save_stage_overrides(profile_name, payload)
    if body.set_as_default:
        set_active_profile_name(profile_name)
    elif body.active_profile:
        # Backward compat for older WebUI clients that always sent active_profile.
        set_active_profile_name(body.active_profile)
    return get_profile_stages_for_ui(profile_name)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def main() -> None:
    import uvicorn

    host = os.environ.get("ORCHESTRATOR_WEBUI_HOST", "127.0.0.1")
    port = int(os.environ.get("ORCHESTRATOR_WEBUI_PORT", "18068"))
    uvicorn.run(
        "orchestrator_mcp.webui.app:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
