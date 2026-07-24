const toastEl = document.getElementById("toast");

function esc(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/"/g, "&quot;");
}

function toast(msg, ms = 2600) {
  toastEl.textContent = msg;
  toastEl.classList.remove("hidden");
  setTimeout(() => toastEl.classList.add("hidden"), ms);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((el) => {
    el.classList.toggle("active", el.dataset.tab === name);
  });
  document.querySelectorAll(".panel").forEach((el) => {
    el.classList.toggle("active", el.id === `panel-${name}`);
  });
}

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

function providerCard(p) {
  const title = p.label_zh || p.provider;
  const vendor = p.vendor_zh ? `<span class="vendor">${esc(p.vendor_zh)}</span>` : "";
  const alias = p.aliases?.length
    ? `<span class="alias">别名 ${esc(p.aliases.join(" / "))}</span>`
    : "";
  const source = p.source_label_zh || p.source;
  const badge = p.configured
    ? `<span class="badge ok">已配置 · ${esc(source)}</span>`
    : `<span class="badge warn">未配置</span>`;
  const suggestions = (p.model_suggestions || [])
    .map((m) => `<option value="${esc(m)}"></option>`)
    .join("");
  const desc = p.description_zh
    ? `<p class="card-desc">${esc(p.description_zh)}</p>`
    : "";
  const wireBlock =
    p.provider === "openai" || p.provider === "codex-lb" || p.wire_api === "responses"
      ? `
      <div class="field">
        <label>协议 Wire API</label>
        <select name="wire_api">
          <option value="chat" ${p.wire_api === "chat" ? "selected" : ""}>chat — Chat Completions (/chat/completions)</option>
          <option value="responses" ${p.wire_api === "responses" ? "selected" : ""}>responses — Codex Responses (/responses, SSE)</option>
        </select>
        <small>${esc(p.wire_api_label_zh || "")}</small>
      </div>
      <div class="field">
        <label>推理强度 Reasoning Effort</label>
        <select name="reasoning_effort">
          <option value="" ${!p.reasoning_effort ? "selected" : ""}>默认</option>
          <option value="low" ${p.reasoning_effort === "low" ? "selected" : ""}>low</option>
          <option value="medium" ${p.reasoning_effort === "medium" ? "selected" : ""}>medium</option>
          <option value="high" ${p.reasoning_effort === "high" ? "selected" : ""}>high</option>
        </select>
        <small>仅 wire_api=responses 时生效（如 gpt-5.4 / Codex 中转）。</small>
      </div>`
      : "";

  const namingHint = p.naming_pattern
    ? `<small class="naming-hint">命名：${esc(p.naming_pattern)}${p.naming_examples ? ` · 例 ${esc(p.naming_examples)}` : ""}</small>`
    : "";
  const customList =
    (p.custom_models || []).length > 0
      ? `<small class="muted">已添加自定义：${esc((p.custom_models || []).join(", "))}</small>`
      : "";

  return `
    <article class="card" data-provider="${esc(p.provider)}">
      <div class="card-head">
        <h2>${esc(title)} <code class="id">${esc(p.provider)}</code></h2>
        ${vendor}${alias}
      </div>
      ${desc}
      ${badge}
      <div class="field">
        <label>API 密钥 ${p.api_key_hint ? `<span class="muted">(当前 ${esc(p.api_key_hint)})</span>` : ""}</label>
        <input type="password" name="api_key" placeholder="留空则不修改" autocomplete="off" />
        <small>环境变量：<code>${esc(p.env_var)}</code></small>
      </div>
      <div class="field">
        <label>API 地址 (Base URL)</label>
        <input type="text" name="base_url" value="${esc(p.base_url || "")}" />
      </div>
      <div class="field">
        <label>默认模型 (Default Model)</label>
        <div class="model-picker">
          <input type="text" name="default_model" list="models-${esc(p.provider)}" value="${esc(p.default_model || "")}" />
          <button type="button" class="btn-add-model" data-action="add-model" title="将输入的 model ID 加入候选列表">+ 添加</button>
        </div>
        <small>Role 未指定 model 时可作回退；须与厂商 API 文档中的 model 字符串完全一致（通常全小写）。</small>
        ${namingHint}
        ${customList}
        <datalist id="models-${esc(p.provider)}">${suggestions}</datalist>
      </div>
      ${wireBlock}
      <div class="card-actions">
        <button class="primary save-provider">保存</button>
        <button class="danger clear-key">清除本地密钥</button>
      </div>
    </article>
  `;
}

async function loadProviders() {
  const { providers } = await api("/api/providers");
  const grid = document.getElementById("providers-grid");
  grid.innerHTML = providers.map(providerCard).join("");
  grid.querySelectorAll(".save-provider").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const card = btn.closest(".card");
      const provider = card.dataset.provider;
      const body = {
        api_key: card.querySelector('[name="api_key"]').value || null,
        base_url: card.querySelector('[name="base_url"]').value,
        default_model: card.querySelector('[name="default_model"]').value,
      };
      const wireEl = card.querySelector('[name="wire_api"]');
      const effortEl = card.querySelector('[name="reasoning_effort"]');
      if (wireEl) body.wire_api = wireEl.value;
      if (effortEl) body.reasoning_effort = effortEl.value;
      await api(`/api/providers/${provider}`, { method: "PUT", body: JSON.stringify(body) });
      card.querySelector('[name="api_key"]').value = "";
      toast(`${provider} 厂商配置已保存`);
      await loadProviders();
    });
  });
  grid.querySelectorAll(".clear-key").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const card = btn.closest(".card");
      const provider = card.dataset.provider;
      await api(`/api/providers/${provider}`, {
        method: "PUT",
        body: JSON.stringify({ clear_api_key: true }),
      });
      toast(`${provider} 本地密钥已清除`);
      await loadProviders();
    });
  });
  grid.querySelectorAll('[data-action="add-model"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      const card = btn.closest(".card");
      const provider = card.dataset.provider;
      const input = card.querySelector('[name="default_model"]');
      try {
        const added = await addProviderModel(provider, input?.value || "");
        if (added) {
          if (input) input.value = added;
          toast(`已添加模型 ${added}`);
          await loadProviders();
        }
      } catch (e) {
        toast(e.message, 5000);
      }
    });
  });
}

let providerOptions = [];
let providerModels = {};
let profilesCache = [];
let activeProfileName = "daily-dev";

function syncDefaultCheckbox(profileName) {
  const checkbox = document.getElementById("set-default-profile");
  if (!checkbox) return;
  checkbox.checked = profileName === activeProfileName;
}

function updateActiveProfileHint() {
  const hint = document.getElementById("active-profile-hint");
  if (!hint) return;
  const active = profilesCache.find((p) => p.name === activeProfileName);
  const label = active?.label_zh || activeProfileName;
  hint.innerHTML = `当前 MCP 默认 Profile：<strong>${esc(label)}</strong> <code>${esc(activeProfileName)}</code>（<code>orchestrate_run_start</code> 未传 profile 时使用）`;
}

function providerOptionLabel(o) {
  const zh = o.label_zh || o.id;
  const alias = o.aliases?.length ? ` · ${o.aliases.join("/")}` : "";
  return `${zh} (${o.id}${alias})`;
}

function defaultModelForProvider(providerId) {
  const meta = providerModels[providerId] || {};
  return meta.default_model || (meta.model_suggestions || [])[0] || "";
}

function modelChoicesForProvider(providerId) {
  const meta = providerModels[providerId] || {};
  const choices = [];
  const seen = new Set();
  for (const item of [
    meta.default_model,
    ...(meta.custom_models || []),
    ...(meta.model_suggestions || []),
  ]) {
    const text = String(item || "").trim();
    if (!text || seen.has(text)) continue;
    seen.add(text);
    choices.push(text);
  }
  return choices;
}

async function addProviderModel(providerId, modelId) {
  const meta = providerModels[providerId] || {};
  const hintParts = [
    meta.naming_pattern && `格式：${meta.naming_pattern}`,
    meta.naming_examples && `示例：${meta.naming_examples}`,
    meta.naming_note && `说明：${meta.naming_note}`,
  ].filter(Boolean);
  const preset = (modelId || "").trim();
  const value = window.prompt(
    `输入 ${providerId} 的 model ID（须与 API 文档完全一致）${hintParts.length ? "\n\n" + hintParts.join("\n") : ""}`,
    preset
  );
  if (!value?.trim()) return null;
  const data = await api(`/api/providers/${encodeURIComponent(providerId)}/models`, {
    method: "POST",
    body: JSON.stringify({ model: value.trim() }),
  });
  mergeProviderModelMeta(providerId, data.provider || {});
  return data.added_model || value.trim();
}

function mergeProviderModelMeta(providerId, row) {
  if (!row || !providerId) return;
  providerModels[providerId] = {
    ...(providerModels[providerId] || {}),
    default_model: row.default_model ?? providerModels[providerId]?.default_model,
    model_suggestions: row.model_suggestions || providerModels[providerId]?.model_suggestions || [],
    custom_models: row.custom_models || providerModels[providerId]?.custom_models || [],
    naming_pattern: row.naming_pattern ?? providerModels[providerId]?.naming_pattern,
    naming_examples: row.naming_examples ?? providerModels[providerId]?.naming_examples,
    naming_note: row.naming_note ?? providerModels[providerId]?.naming_note,
  };
}

function modelSelectHtml(providerId, selectedModel, extraModels = []) {
  const choices = modelChoicesForProvider(providerId);
  for (const item of extraModels) {
    const text = String(item || "").trim();
    if (text && !choices.includes(text)) choices.push(text);
  }
  const fallback = defaultModelForProvider(providerId);
  const current = (selectedModel || "").trim() || fallback;
  if (choices.length === 0) {
    return `<select name="model"><option value="${esc(fallback)}">${esc(fallback || "（无可用模型）")}</option></select>`;
  }
  const options = choices
    .map((model) => {
      const selected = model === current ? " selected" : "";
      return `<option value="${esc(model)}"${selected}>${esc(model)}</option>`;
    })
    .join("");
  return `<select name="model">${options}</select>`;
}

function modelPickerHtml(providerId, selectedModel, extraModels = []) {
  return `<div class="model-picker">${modelSelectHtml(providerId, selectedModel, extraModels)}<button type="button" class="btn-add-model" data-action="add-role-model" title="添加自定义 model ID 到该厂商列表">+ 添加</button></div>`;
}

function refreshRoleModelSelect(row, providerId, preferredModel) {
  const cell = row.querySelector(".model-cell");
  if (!cell) return;
  const nextModel = preferredModel || defaultModelForProvider(providerId);
  const warn = cell.querySelector(".cell-warn");
  const warnHtml = warn ? warn.outerHTML : "";
  cell.innerHTML = `${modelPickerHtml(providerId, nextModel)}${warnHtml}`;
  bindModelSelectEvents(row);
  bindRoleAddModelButton(row);
  updateRowMismatchState(row);
}

function updateRowMismatchState(row) {
  const providerSelect = row.querySelector('[name="provider"]');
  const modelSelect = row.querySelector('[name="model"]');
  if (!providerSelect || !modelSelect) return;
  const valid = modelValidForProvider(providerSelect.value, modelSelect.value);
  row.classList.toggle("model-mismatch", !valid);
  const warn = row.querySelector(".cell-warn");
  if (valid) {
    warn?.remove();
    return;
  }
  if (!warn) {
    const cell = row.querySelector(".model-cell");
    const note = document.createElement("div");
    note.className = "cell-warn";
    note.innerHTML = `当前模型与厂商不匹配，请重新选择后保存`;
    cell.appendChild(note);
  }
}

function bindModelSelectEvents(row) {
  const modelSelect = row.querySelector('[name="model"]');
  if (!modelSelect) return;
  if (modelSelect.dataset.bound) return;
  modelSelect.dataset.bound = "1";
  modelSelect.addEventListener("change", () => updateRowMismatchState(row));
}

function modelValidForProvider(providerId, model) {
  const meta = providerModels[providerId] || {};
  const text = (model || "").trim();
  if (!text) return false;
  if (text === meta.default_model) return true;
  if ((meta.model_suggestions || []).includes(text)) return true;
  const prefixes = {
    deepseek: "deepseek",
    moonshot: "moonshot",
    zhipu: "glm",
    openai: "gpt",
    "codex-lb": "gpt",
    stub: "stub",
  };
  const extraPrefixes = {
    moonshot: ["kimi-"],
  };
  const prefix = prefixes[providerId];
  if (prefix && text.startsWith(prefix)) return true;
  for (const extra of extraPrefixes[providerId] || []) {
    if (text.startsWith(extra)) return true;
  }
  if (providerId === "openai" && text.startsWith("o")) return true;
  if ((meta.custom_models || []).includes(text)) return true;
  return false;
}

function bindRoleAddModelButton(row) {
  const btn = row.querySelector('[data-action="add-role-model"]');
  if (!btn || btn.dataset.bound) return;
  btn.dataset.bound = "1";
  btn.addEventListener("click", async () => {
    const providerSelect = row.querySelector('[name="provider"]');
    const modelSelect = row.querySelector('[name="model"]');
    if (!providerSelect) return;
    try {
      const added = await addProviderModel(providerSelect.value, modelSelect?.value || "");
      if (!added) return;
      refreshRoleModelSelect(row, providerSelect.value, added);
      toast(`已添加并选中 ${added}`);
    } catch (e) {
      toast(e.message, 5000);
    }
  });
}

function roleRow(s) {
  const options = providerOptions
    .map((o) => {
      const selected = o.id === s.provider ? "selected" : "";
      return `<option value="${esc(o.id)}" ${selected}>${esc(providerOptionLabel(o))}</option>`;
    })
    .join("");
  const override = s.overridden ? ' <span class="override" title="已被本地 roles.local.json 覆盖">*</span>' : "";
  const roleTitle = s.label_zh || s.role;
  const roleDesc = s.description_zh
    ? `<div class="cell-desc">${esc(s.description_zh)}</div>`
    : "";
  const schemaTitle = s.schema_label_zh || s.output_schema;
  const displayModel = s.model_mismatch ? s.suggested_model || defaultModelForProvider(s.provider) : s.model || "";
  const mismatchNote = s.model_mismatch
    ? `<div class="cell-warn">本地保存 <code>${esc(s.model)}</code> 与 ${esc(s.provider_label_zh || s.provider)} 不匹配，请重新选择后保存</div>`
    : "";

  return `
    <tr data-role="${esc(s.role)}" class="${s.model_mismatch ? "model-mismatch" : ""}" data-saved-model="${esc(s.model || "")}">
      <td>
        <strong>${esc(roleTitle)}</strong>${override}
        <div class="cell-meta"><code>${esc(s.role)}</code></div>
        ${roleDesc}
      </td>
      <td><select name="provider">${options}</select></td>
      <td class="model-cell">
        ${modelPickerHtml(s.provider, displayModel, s.model_mismatch ? [displayModel] : [])}
        ${mismatchNote}
      </td>
      <td>
        <div>${esc(schemaTitle)}</div>
        <div class="cell-meta"><code>${esc(s.output_schema)}</code></div>
      </td>
    </tr>
  `;
}

function bindRoleRowEvents() {
  document.querySelectorAll("#roles-body tr").forEach((row) => {
    const providerSelect = row.querySelector('[name="provider"]');
    if (!providerSelect || providerSelect.dataset.bound) return;
    providerSelect.dataset.bound = "1";
    providerSelect.addEventListener("change", () => {
      refreshRoleModelSelect(row, providerSelect.value);
    });
    bindModelSelectEvents(row);
    bindRoleAddModelButton(row);
    updateRowMismatchState(row);
  });
}

function renderProfileDesc(profileName, roleData) {
  const box = document.getElementById("profile-desc");
  const fromList = profilesCache.find((p) => p.name === profileName);
  const title = roleData?.label_zh || fromList?.label_zh || profileName;
  const desc = roleData?.description_zh || fromList?.description_zh || fromList?.description || "";
  box.innerHTML = `
    <strong>${esc(title)}</strong>
    <span class="cell-meta"><code>${esc(profileName)}</code></span>
    <p>${esc(desc)}</p>
  `;
}

async function loadRoles(profileName) {
  const data = await api(`/api/profiles/${encodeURIComponent(profileName)}/roles`);
  providerOptions = data.provider_options || [];
  providerModels = data.provider_models || {};
  const tbody = document.getElementById("roles-body");
  tbody.innerHTML = (data.roles || []).map(roleRow).join("");
  bindRoleRowEvents();
  renderProfileDesc(profileName, data);
  const mismatches = (data.roles || []).filter((s) => s.model_mismatch).length;
  if (mismatches) {
    toast(`有 ${mismatches} 个 Role 的模型与厂商不匹配，已填入建议值，请确认后保存`, 4200);
  }
}

async function loadProfiles() {
  const { profiles, active_profile } = await api("/api/profiles");
  profilesCache = profiles || [];
  activeProfileName = active_profile || profilesCache.find((p) => p.is_active)?.name || "daily-dev";
  const select = document.getElementById("profile-select");
  select.innerHTML = profilesCache
    .map((p) => {
      const defaultMark = p.is_active ? " ★默认" : "";
      const label = p.label_zh ? `${p.label_zh} (${p.name})${defaultMark}` : `${p.name}${defaultMark}`;
      return `<option value="${esc(p.name)}" title="${esc(p.description_zh || p.description || "")}">${esc(label)}</option>`;
    })
    .join("");
  select.value = activeProfileName;
  if (!select.dataset.bound) {
    select.dataset.bound = "1";
    select.addEventListener("change", () => {
      syncDefaultCheckbox(select.value);
      loadRoles(select.value);
    });
    document.getElementById("set-default-profile")?.addEventListener("change", () => {
      /* user toggles intent before save */
    });
  }
  syncDefaultCheckbox(select.value);
  updateActiveProfileHint();
  await loadRoles(select.value);
}

document.getElementById("save-roles").addEventListener("click", async () => {
  const select = document.getElementById("profile-select");
  const profile = select.value;
  const setAsDefault = document.getElementById("set-default-profile")?.checked ?? false;
  const roles = {};
  document.querySelectorAll("#roles-body tr").forEach((row) => {
    const role = row.dataset.role;
    const provider = row.querySelector('[name="provider"]').value;
    let model = row.querySelector('[name="model"]').value.trim();
    if (!modelValidForProvider(provider, model)) {
      model = defaultModelForProvider(provider);
      refreshRoleModelSelect(row, provider, model);
    }
    roles[role] = { provider, model };
  });
  await api(`/api/profiles/${encodeURIComponent(profile)}/roles`, {
    method: "PUT",
    body: JSON.stringify({ roles, set_as_default: setAsDefault }),
  });
  const label = profilesCache.find((p) => p.name === profile)?.label_zh || profile;
  const defaultNote = setAsDefault ? "，并已设为 MCP 默认 Profile" : "（未更改 MCP 默认 Profile）";
  toast(`编排方案「${label}」Role 配置已保存${defaultNote}`);
  if (setAsDefault) {
    activeProfileName = profile;
  }
  const refreshed = await api("/api/profiles");
  profilesCache = refreshed.profiles || [];
  activeProfileName = refreshed.active_profile || activeProfileName;
  select.innerHTML = profilesCache
    .map((p) => {
      const defaultMark = p.is_active ? " ★默认" : "";
      const label = p.label_zh ? `${p.label_zh} (${p.name})${defaultMark}` : `${p.name}${defaultMark}`;
      return `<option value="${esc(p.name)}" title="${esc(p.description_zh || p.description || "")}">${esc(label)}</option>`;
    })
    .join("");
  select.value = profile;
  syncDefaultCheckbox(profile);
  updateActiveProfileHint();
  await loadRoles(profile);
});

loadProviders().catch((e) => toast(e.message, 5000));
loadProfiles().catch((e) => toast(e.message, 5000));

function renderGuide(info) {
  const mcpStatus = info.mcp_reachable
    ? `<span class="status-pill ok">MCP 进程可达</span>`
    : `<span class="status-pill warn">MCP 未启动 — 请运行 ./start.sh</span>`;
  const tools = (info.tools || [])
    .map(
      (t) => `
      <li>
        <strong>${esc(t.name)}</strong>
        ${t.label_zh ? `<span class="muted"> · ${esc(t.label_zh)}</span>` : ""}
        <p>${esc(t.desc_zh || "")}</p>
      </li>`
    )
    .join("");
  const shells = (info.shell_commands || [])
    .map(
      (s) => `
      <div class="cmd-block">
        <code>${esc(s.cmd)}</code>
        <p class="cell-desc">${esc(s.desc_zh || "")}</p>
      </div>`
    )
    .join("");
  const notes = (info.notes_zh || []).map((n) => `<li>${esc(n)}</li>`).join("");
  const cursorJson = JSON.stringify(info.cursor_mcp_config || {}, null, 2);

  document.getElementById("guide-content").innerHTML = `
    <div class="guide-card">
      <h2>服务信息</h2>
      <div class="status-row">
        ${mcpStatus}
        <span class="status-pill">服务 ID：<code>orchestrator-mcp</code></span>
      </div>
      <p class="cell-desc">MCP 地址：<code>${esc(info.mcp_url)}</code></p>
      <p class="cell-desc">WebUI 地址：<code>${esc(info.webui_url)}</code></p>
      <p class="cell-desc">配置目录：<code>${esc(info.data_dir)}</code></p>
    </div>

    <div class="guide-card">
      <h2>终端常用命令</h2>
      ${shells}
    </div>

    <div class="guide-card">
      <h2>Cursor MCP 配置</h2>
      <p class="cell-desc">Settings → MCP → 添加 server 名 <code>orchestrator-mcp</code>：</p>
      <div class="cmd-block"><code>${esc(cursorJson)}</code></div>
    </div>

    <div class="guide-card">
      <h2>MCP 工具（在 Cursor Agent 里调用）</h2>
      <ul class="tool-list">${tools}</ul>
      <p class="cell-desc">典型用法：先用 <code>orchestrate_run_start(goal, role="ui_review")</code> 创建单角色审查任务，再用 <code>orchestrate_dispatch(run_id)</code> 执行；每个 run 只绑定一个 Review 角色。</p>
    </div>

    <div class="guide-card">
      <h2>WebUI 与 MCP 的关系</h2>
      <ul class="notes-list">${notes}</ul>
    </div>
  `;
}

async function loadGuide() {
  const info = await api("/api/info");
  renderGuide(info);
}

loadGuide().catch((e) => {
  document.getElementById("guide-content").innerHTML = `<p class="hint">加载失败：${esc(e.message)}</p>`;
});
