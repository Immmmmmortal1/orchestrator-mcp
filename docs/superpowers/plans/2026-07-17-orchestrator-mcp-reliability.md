# Orchestrator MCP Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将一周内反复断连的评审 MCP 收口到唯一代码源、可自愈虚拟环境和可验收的 stdio/HTTP 生命周期模型。

**Architecture:** `/Users/xiaomao11/project/orchestrator-mcp` 是唯一源码与运行根目录。Codex 使用按 `CODEX_THREAD_ID` 隔离的 stdio 子进程；launchd 可保留独立的 streamable-http 服务供 URL 客户端使用；WebUI 独立监听 18068。安装脚本统一生成 Codex 配置和 launchd plist，doctor 同时检查源码路径、venv、进程、端口、会话注册和协议能力。

**Tech Stack:** Python 3.10+、FastMCP、Bash、launchd、unittest、MCP stdio/streamable-http

---

### Task 1: Repair relocatable virtual environment bootstrap

**Files:**
- Modify: `ensure-venv.sh`
- Test: `verify.sh`

- [ ] 以当前 `./verify.sh` 的坏 shebang 失败作为 RED 证据。
- [ ] 改为始终通过 `venv/bin/python -m pip` 安装，避免复制/迁移后 pip shebang 失效。
- [ ] 重新运行 `./verify.sh`，确认规范仓库自检通过。

### Task 2: Add per-session stdio ownership and regression tests

**Files:**
- Create: `src/orchestrator_mcp/session_runtime.py`
- Create: `codex-stdio-wrapper.sh`
- Create: `tests/test_session_runtime.py`
- Modify: `src/orchestrator_mcp/server.py`

- [ ] 先创建测试，覆盖不同 session 共存、同 session 替换、旧实例清理不删除新记录、进程指纹健康检查。
- [ ] 运行测试，确认因模块/行为缺失而失败。
- [ ] 实现 session 注册、文件锁、实例所有权、退出清理和 replacement watchdog。
- [ ] 在 stdio 启动时注册并安装退出处理器。
- [ ] 运行定向测试和全量自检。

### Task 3: Add deployment doctor and installer

**Files:**
- Create: `scripts/orchestrator-doctor.sh`
- Create: `scripts/install-local.sh`
- Create: `tests/test_installation_contract.py`
- Modify: `README.md`

- [ ] 先写安装契约测试，要求所有路径都指向规范仓库、Codex transport 为 stdio、launchd HTTP/WebUI 端口分离。
- [ ] 运行测试，确认缺少脚本而失败。
- [ ] 实现幂等安装脚本：备份后更新 Codex orchestrator 段、生成/加载 launchd plist、停止旧目录实例。
- [ ] 实现 doctor：验证 repo/venv/config/plist/进程/端口，并输出机器可读摘要。
- [ ] 运行安装契约测试。

### Task 4: Migrate live configuration and retire stale runtime

**Files:**
- Modify: `~/.codex/config.toml`
- Modify: `~/Library/LaunchAgents/com.xiaomao11.orchestrator-mcp.plist`
- Modify: `~/Library/LaunchAgents/com.xiaomao11.orchestrator-webui.plist`

- [ ] 保存旧配置备份，不删除旧源码目录。
- [ ] 执行幂等安装脚本，统一路径到规范仓库。
- [ ] 卸载旧 launchd job，加载规范 job。
- [ ] 停止旧目录残留实例，并确认只剩规范 HTTP/WebUI 实例。
- [ ] 说明当前 Codex 会话不会热注册新工具，需要新任务验收。

### Task 5: Protocol and real-review acceptance

**Files:**
- Test: `verify.sh`
- Test: `scripts/orchestrator-doctor.sh`

- [ ] 运行 compile/self-test/unit tests。
- [ ] 通过 MCP stdio 初始化并列出 `orchestrate_*` 工具。
- [ ] 通过 streamable-http 初始化/工具列表验证 18067。
- [ ] 检查 Provider 配置状态，区分服务、鉴权与模型调用错误。
- [ ] 执行一次 stub code review；Provider 可用时再执行一次真实 code review。
- [ ] 汇总验证证据、未完成项和新会话要求。
