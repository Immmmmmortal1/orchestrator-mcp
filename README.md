# orchestrator-mcp

多模型 **Agent 编排 MCP**：`plan → code → review → deliver`。

- **Handoff schema 固定**（`schemas/`）
- **Provider 按厂商**（deepseek / moonshot / zhipu / openai），**model 按 stage 配置**
- **别名**：`glm` → zhipu，`gpt` → openai
- **凭证**：环境变量 → WebUI 本地 JSON → `~/Desktop/服务器.md`
- **Web 配置界面**：编辑 Provider Key / Base URL / 默认模型，以及各 Profile 的 Stage 模型

## 快速开始

```bash
cd orchestrator-mcp
./verify.sh              # 离线 stub 自测（含 WebUI API 冒烟）
./start.sh               # MCP :18067
./start-webui.sh         # 配置 WebUI :18068 → http://127.0.0.1:18068

# 可选：只测 plan 阶段真实 DeepSeek 调用
ORCHESTRATOR_LIVE_TEST=1 ./verify.sh
```

## Web 配置界面

| 功能 | 说明 |
|------|------|
| Providers | 编辑 `api_key`、`base_url`、`default_model`；写入 `data/providers.local.json` |
| Stages | 按 Profile 覆盖 plan/code/review/deliver 的 provider + model；写入 `data/stages.local.json` |

本地配置文件**不进 git**。环境变量仍优先于 WebUI 写入的值。

## Profile

| Profile | 用途 |
|---------|------|
| `daily-dev-stub` | 离线自测，不调 API |
| `daily-dev` | deepseek plan / glm code / gpt review / moonshot deliver |
| `example-kimi-plan` | 示例：plan 换 kimi |

同一 OpenAI 账号下 plan 用 `gpt-4o-mini`、code 用 `gpt-5`：只改 YAML 里各 stage 的 `model`，**不用**建两个 provider。

```yaml
stages:
  plan:
    provider: gpt
    model: gpt-4o-mini
  code:
    provider: gpt
    model: gpt-5
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

Stage 里把 review/deliver 的 provider 选 **codex-lb**（或别名 **codex**），model 填 `gpt-5.4`。

**注意**：`/chat/completions` 在该中转上返回 405；必须用 Responses 协议。

可选覆盖：`CODEX_LB_BASE_URL`、`DEEPSEEK_BASE_URL`、`MOONSHOT_BASE_URL`、`ZHIPU_BASE_URL`、`OPENAI_BASE_URL`

`服务器.md` 标签（下一行或同行）：`deepseekApiKey`、`moonshotApiKey`、`zhipuApiKey`、`openaiApiKey`

## MCP 工具

| 工具 | 说明 |
|------|------|
| `orchestrate_list_providers` | 各 provider 是否已配置 key |
| `orchestrate_provider_check` | 检查单个 provider |
| `orchestrate_run_start` / `orchestrate_dispatch` / `orchestrate_run_pipeline` | 编排执行 |
| `orchestrate_stage_override` | 运行时换 provider/model |

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
