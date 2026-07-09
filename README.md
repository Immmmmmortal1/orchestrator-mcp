# orchestrator-mcp

多模型 **审查 MCP**：按角色拆分 UI 审查、代码审查、通用审查。

- **Handoff schema 固定**（`schemas/`）
- **Provider 按厂商**（deepseek / moonshot / zhipu / openai / codex-lb），**model 按 stage 配置**
- **别名**：`glm` → zhipu，`gpt` → openai
- **凭证**：环境变量 → WebUI 本地 JSON → `~/Desktop/服务器.md`
- **Web 配置界面**：编辑 Provider Key / Base URL / 默认模型，以及各 Profile 的 Stage 模型

## 快速开始

```bash
cd orchestrator-mcp
./verify.sh              # 离线 stub 自测（含 WebUI API 冒烟）
./start.sh               # MCP :18067
./start-webui.sh         # 配置 WebUI :18068 → http://127.0.0.1:18068

# 可选：只测 review 阶段真实模型调用
ORCHESTRATOR_LIVE_TEST=1 ./verify.sh
```

## Web 配置界面

| 功能 | 说明 |
|------|------|
| Providers | 编辑 `api_key`、`base_url`、`default_model`；写入 `data/providers.local.json` |
| Stages | 按 Profile 覆盖 `ui_review` / `code_review` / `general_review` 的 provider + model；写入 `data/stages.local.json` |

本地配置文件**不进 git**。环境变量仍优先于 WebUI 写入的值。

## Profile

| Profile | 用途 |
|---------|------|
| `daily-dev-stub` | 离线三角色审查自测，不调 API |
| `daily-dev` | 日常三角色审查 |
| `example-kimi-plan` | 多模型审查示例，不同角色用不同模型 |

同一厂商下切换模型：只改 YAML 或 WebUI Stages 里的 `model`，**不用**建两个 provider。

```yaml
stages:
  ui_review:
    provider: codex-lb
    model: gpt-5.4
  code_review:
    provider: codex-lb
    model: gpt-5.4
  general_review:
    provider: deepseek
    model: deepseek-v4-flash
```

## 凭证环境变量

| Provider | Env | 默认 Base URL |
|----------|-----|---------------|
| deepseek | `DEEPSEEK_API_KEY` | https://api.deepseek.com/v1 |
| moonshot | `MOONSHOT_API_KEY` | https://api.moonshot.cn/v1 |
| zhipu/glm | `ZHIPU_API_KEY` | https://open.bigmodel.cn/api/paas/v4 |
| openai/gpt | `OPENAI_API_KEY` | https://api.openai.com/v1 · `wire_api=chat` |
| codex-lb/codex | `CODEX_LB_API_KEY` | https://codex-lb.vvicat.dev/backend-api/codex · `wire_api=responses` |

### Codex 中转（Responses API）

与 Codex CLI 配置对应关系：

```toml
model = "gpt-5.4"
model_reasoning_effort = "medium"
model_provider = "codex-lb"
env_key = "CODEX_LB_API_KEY"

[model_providers.codex-lb]
base_url = "https://codex-lb.vvicat.dev/backend-api/codex"
wire_api = "responses"
```

在 WebUI **Providers → Codex 中转** 填写：

| 字段 | 值 |
|------|-----|
| API 密钥 | 同 `CODEX_LB_API_KEY` |
| Base URL | `https://codex-lb.vvicat.dev/backend-api/codex`（不要写成 `/code`） |
| 默认模型 | `gpt-5.4` |
| Wire API | `responses` |
| Reasoning Effort | `medium` |

Stage 里可把 `ui_review` / `code_review` 的 provider 选 **codex-lb**（或别名 **codex**），model 填 `gpt-5.4`。

**注意**：`/chat/completions` 在该中转上返回 405；必须用 Responses 协议。

可选覆盖：`CODEX_LB_BASE_URL`、`DEEPSEEK_BASE_URL`、`MOONSHOT_BASE_URL`、`ZHIPU_BASE_URL`、`OPENAI_BASE_URL`

`服务器.md` 标签（下一行或同行）：`deepseekApiKey`、`moonshotApiKey`、`zhipuApiKey`、`openaiApiKey`

## Workspace 项目上下文（与 IDE 共用源文件）

MCP **不单独维护**记忆文件。传入 `workspace`（或设置 `ORCHESTRATOR_WORKSPACE`）后，每个 stage **直接从磁盘读取**与 Cursor/Codex 相同的源文件并注入 prompt：

| 路径 | 说明 |
|------|------|
| `AGENTS.md` / `CLAUDE.md` / `agent.md` | 项目级 agent 说明 |
| `.cursor/rules/*` | Cursor 规则 |
| `.learnings/*.md` | self-improving 沉淀 |
| profile `skills:` | 加载对应 `SKILL.md` 全文 |
| git | branch、dirty files、diff --stat |

- `orchestrate_run_start` / `orchestrate_run_pipeline`：`workspace`、`extra_context`（仅本次 run）
- `orchestrate_workspace_context`：预览将读取哪些文件

## MCP 工具

| 工具 | 说明 |
|------|------|
| `orchestrate_list_providers` | 各 provider 是否已配置 key |
| `orchestrate_provider_check` | 检查单个 provider |
| `orchestrate_effective_config` | 不调用模型，查看 MCP 当前实际会用的 profile / stage / provider / model |
| `orchestrate_workspace_context` | 预览 workspace 项目上下文 |
| `orchestrate_run_start` / `orchestrate_dispatch` / `orchestrate_run_pipeline` | 编排执行（支持 `workspace`） |
| `orchestrate_stage_override` | 运行时换 provider/model |

### Provider 选择规则

- Providers 页只表示“这个厂商已配置 key / base_url / 默认模型”。
- 真正决定 MCP 执行使用哪个 provider 的是 Stages 页；保存后写入 `data/stages.local.json`。
- 调用前可先跑 `orchestrate_effective_config(stage="ui_review")`，确认有效配置，避免误跑到 YAML 默认值。
- `orchestrate_run_pipeline(stage="ui_review")` 只跑 UI 审查；不传 `stage` 时依次跑三类审查。
- `stage_overrides_json` 支持短写：`{"provider":"codex-lb","model":"gpt-5.4"}` 或 `{"code_review":{"model":"codex/gpt-5.4"}}`。
- 兼容旧入参：`review` 会映射到 `general_review`。

## Cursor 配置

本仓库已在 **`.cursor/mcp.json`** 写好配置（stdio 模式，**不用**手动 `./start.sh`）。

1. 用 Cursor 打开 **`localopenclaw`** 仓库根目录  
2. **Settings → Tools & MCP**，确认 **orchestrator-mcp** 已启用（绿点）  
3. 若没有，点 **Refresh** 或重启 Cursor  

若仍看不到：Settings → MCP → **Edit Config**，确认项目级 `.cursor/mcp.json` 已加载。

**方式 A（推荐，已写入项目）**：Cursor 自动拉起进程

```json
{
  "mcpServers": {
    "orchestrator-mcp": {
      "command": ".../orchestrator-mcp/.venv/bin/python",
      "args": ["-m", "orchestrator_mcp"],
      "env": {
        "PYTHONPATH": ".../orchestrator-mcp/src",
        "ORCHESTRATOR_MCP_TRANSPORT": "stdio"
      }
    }
  }
}
```

**方式 B**：先 `./start.sh`，再用 URL（需保持终端进程运行）

```json
{
  "mcpServers": {
    "orchestrator-mcp": {
      "url": "http://127.0.0.1:18067/mcp"
    }
  }
}
```
