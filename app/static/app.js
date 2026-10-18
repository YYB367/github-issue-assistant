"use strict";
const $ = (id) => document.getElementById(id),
  S = {
    s: null,
    op: null,
    health: null,
    busy: false,
    offset: 0,
    timer: null,
    polls: 0,
  };
const names = {
  installation: "安装问题",
  dependency: "依赖问题",
  configuration: "配置问题",
  other: "其他",
  unclear: "尚不明确",
  running: "分析中",
  completed: "分析完成",
  failed: "失败",
  timed_out: "超时",
  cancelled: "已取消",
  previewed: "待确认",
  confirmed: "已确认",
  executing: "执行中",
  succeeded: "成功",
  unknown: "结果未知",
  invalidated: "已失效",
};
const messages = {
  revision_conflict: "会话已变化，请刷新后重新检查。",
  confirmation_expired: "确认过期，请重新预览。",
  duplicate_completed_operation: "相同内容已执行成功，请查看记录。",
  unresolved_write_on_issue: "此 Issue 有执行中或结果未知的操作，请先核对。",
  writes_disabled: "写入未开启。",
  example_is_read_only: "公开示例和教学案例始终只读，不能发布评论或标签。",
  restored_state_requires_review: "已恢复旧状态，请先核对GitHub写入历史。",
  github_http_403: "GitHub 拒绝写入，请检查仓库范围和 Issues 写权限。",
  invalid_request: "请求格式不合法，请检查链接、长度和选项。",
};
const pretty = (x) => JSON.stringify(x, null, 2),
  text = (id, v) => ($(id).textContent = v ?? "");
function notice(v, error = false) {
  text("notice", v);
  $("notice").classList.toggle("error", error);
}
function list(id, values) {
  $(id).replaceChildren();
  for (const value of values || []) {
    const li = document.createElement("li");
    li.textContent = value;
    $(id).append(li);
  }
}
function link(el, url, label) {
  el.textContent = label;
  try {
    const u = new URL(url);
    if (
      u.protocol !== "https:" ||
      u.hostname !== "github.com" ||
      u.username ||
      u.password
    )
      throw Error();
    el.href = u.href;
    el.hidden = false;
  } catch {
    el.removeAttribute("href");
  }
}
async function api(path, method = "GET", body) {
  const controller = new AbortController(),
    timer = setTimeout(() => controller.abort(), 50000);
  try {
    const r = await fetch(path, {
        method,
        headers:
          body === undefined ? {} : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      }),
      data = await r.json();
    if (!r.ok) {
      const code =
        typeof data.error === "string" ? data.error : data.error?.code;
      throw Error(
        (messages[code] || code || `HTTP ${r.status}`) +
          `（请求 ${r.headers.get("x-request-id") || "未知"}）`,
      );
    }
    return data;
  } catch (e) {
    if (e.name === "AbortError" || e instanceof TypeError)
      throw Error("连接中断或超时。操作可能已提交，请先刷新状态再决定下一步。");
    throw e;
  } finally {
    clearTimeout(timer);
  }
}
async function action(fn) {
  if (S.busy) return;
  S.busy = true;
  controls();
  try {
    await fn();
  } catch (e) {
    notice(e.message, true);
  } finally {
    S.busy = false;
    controls();
  }
}
function dirty() {
  return !!S.s && $("draft").value !== S.s.draft;
}
function retryable(op) {
  return (
    op?.status === "failed" &&
    ["github_http_401", "github_http_403", "github_http_429"].includes(
      op.error_code,
    ) &&
    op.attempts < 3
  );
}
function controls() {
  const active = !!S.s?.active_task_id,
    executing = S.op?.status === "executing",
    readOnly = Boolean(S.s?.example_id);
  for (const id of [
    "create",
    "restore",
    "refresh",
    "refresh-list",
    "previous",
    "next",
  ])
    $(id).disabled = S.busy;
  for (const id of ["save-draft", "add-supplement", "analyze-again"])
    $(id).disabled = !S.s || S.busy || active || executing;
  for (const id of ["preview-comment", "preview-labels"])
    $(id).disabled =
      !S.s || S.busy || active || executing || dirty() || readOnly;
  $("cancel-task").hidden = !active;
  $("cancel-task").disabled = S.busy;
  $("load-labels").disabled = !S.s || S.busy || readOnly;
  text(
    "draft-status",
    dirty() ? "有未保存修改；保存后重新预览确认" : "草稿已保存",
  );
  const op = S.op,
    eligible =
      op && (["previewed", "confirmed"].includes(op.status) || retryable(op));
  $("confirmation").hidden = !eligible;
  $("confirm-execute").disabled =
    S.busy ||
    readOnly ||
    Boolean(S.storageHold) ||
    dirty() ||
    !eligible ||
    !$("reviewed").checked ||
    $("confirmation-text").value !== op.confirmation_text ||
    (!retryable(op) && Date.parse(op.expires_at) <= Date.now()) ||
    !S.health?.github_writes_enabled ||
    !S.health?.github_token_configured;
  text(
    "confirm-execute",
    retryable(op)
      ? `原因修正后，确认第 ${op.attempts + 1} 次尝试`
      : "确认并执行",
  );
  $("cancel-operation").hidden =
    !op || !["previewed", "confirmed"].includes(op.status);
  $("cancel-operation").disabled = S.busy;
  $("reconcile").hidden = op?.status !== "unknown";
  $("reconcile").disabled = S.busy;
  $("comment-id").hidden =
    op?.status !== "unknown" || op.kind !== "publish_comment";
  $("comment-id-label").hidden = $("comment-id").hidden;
  $("refresh-operation").disabled = S.busy;
}
async function listing() {
  const rows = await api(`/sessions?limit=20&offset=${S.offset}`);
  $("sessions").replaceChildren();
  for (const s of rows) {
    const b = document.createElement("button");
    b.className =
      "session" + (s.session_id === S.s?.session_id ? " active" : "");
    b.textContent = `${s.target.repository.split("/")[1]} #${s.target.issue_number}`;
    const sub = document.createElement("small");
    sub.textContent =
      new Date(s.updated_at).toLocaleString() +
      (s.active_task_id ? " · 分析中" : "");
    b.append(sub);
    b.onclick = () => action(() => open(s.session_id));
    $("sessions").append(b);
  }
  $("previous").hidden = S.offset === 0;
  $("next").hidden = rows.length < 20;
}
async function open(sid) {
  if (dirty()) throw Error("请先保存当前草稿后切换会话。");
  clearTimeout(S.timer);
  S.polls = 0;
  S.s = null;
  S.op = null;
  $("approval").hidden = true;
  const s = await api(`/sessions/${encodeURIComponent(sid)}`);
  S.s = s;
  sessionStorage.setItem("issue-assistant-session", s.session_id);
  $("draft").value = s.draft;
  $("supplement").value = "";
  $("label-panel").hidden = true;
  await refresh();
  await listing();
}
async function refresh() {
  const sid = S.s?.session_id;
  if (!sid) return;
  const s = await api(`/sessions/${sid}`);
  if (S.s?.session_id !== sid) return;
  const wasDirty = dirty();
  S.s = s;
  if (!wasDirty) $("draft").value = s.draft;
  $("workspace").hidden = false;
  link(
    $("target"),
    s.issue_url,
    `${s.target.repository} #${s.target.issue_number}`,
  );
  text("session-meta", `会话 ${s.session_id} · 版本 ${s.revision}`);
  list("supplements", s.supplements);
  let task = null;
  if (s.task_ids.length)
    task = await api(
      `/sessions/${sid}/tasks/${s.active_task_id || s.task_ids.at(-1)}`,
    );
  text("task-state", names[task?.status] || "待分析");
  $("task-error").hidden = !task?.result?.error;
  text("task-error", task?.result?.error?.message || task?.result?.error?.code);
  renderResult(task?.result || s.latest_result);
  const ops = await api(`/sessions/${sid}/operations`);
  $("operations").replaceChildren();
  for (const op of ops.slice().reverse()) {
    const b = document.createElement("button");
    b.className = "session";
    b.textContent = `${op.kind === "publish_comment" ? "发布评论" : "添加标签"} · ${names[op.status]} · 尝试 ${op.attempts}`;
    b.onclick = () =>
      action(async () =>
        showOp(await api(`/sessions/${sid}/operations/${op.operation_id}`)),
      );
    $("operations").append(b);
  }
  if (S.op) {
    const current = ops.find((x) => x.operation_id === S.op.operation_id);
    if (current && pretty(current) !== pretty(S.op)) showOp(current);
  }
  controls();
  document.dispatchEvent(new Event("session-rendered"));
  if (s.active_task_id || ops.some((x) => x.status === "executing")) schedule();
}
function renderResult(r) {
  const a = r?.analysis;
  $("analysis").hidden = !a;
  if (a) {
    text("summary", a.summary);
    text("category", names[a.category]);
    list("known", a.known_information);
    list("missing", a.missing_information);
    list(
      "recommendations",
      (a.recommendations || []).map(
        (x) =>
          `${x.text} ${(x.evidence_ids || []).map((id) => "[" + id + "]").join(" ")}`,
      ),
    );
    text(
      "evidence-status",
      `证据判定：${{ sufficient: "有文档支持，方案仍待验证", partial: "仅有部分支持", insufficient: "证据不足" }[a.evidence_status] || "未使用知识库"}`,
    );
  }
  text("warnings", (r?.warnings || []).join("\n"));
  $("evidence").replaceChildren();
  for (const e of r?.retrieval?.evidence || []) {
    const d = document.createElement("div");
    d.className = "evidence";
    const title = document.createElement("a");
    title.target = "_blank";
    title.rel = "noopener";
    link(title, e.url, `[${e.cite_id}] ${e.title || e.file_path}`);
    const meta = document.createElement("small");
    meta.className = "muted block";
    meta.textContent = `${e.repository} · ${e.file_path} · ${e.version} · 行 ${e.line_start}–${e.line_end}\n${e.source_type === "historical_issue" ? "未经验证的历史报告 · 更新 " + e.updated_at : "固定提交文档"} · ${e.retrieval_method} · cosine distance ${e.distance ?? "不适用"}`;
    const pre = document.createElement("pre");
    pre.textContent = e.text;
    d.append(title, meta, pre);
    $("evidence").append(d);
  }
  if (!r?.retrieval?.evidence?.length) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = "当前没有检索证据。";
    $("evidence").append(p);
  }
  $("trace").replaceChildren();
  for (const t of r?.tool_trace || []) {
    const row = document.createElement("tr");
    for (const value of [
      `${t.name}\n${pretty(t.arguments)}`,
      t.status + (t.error_code ? " / " + t.error_code : ""),
      `${t.elapsed_ms} ms`,
      `${t.result_bytes} B`,
    ]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    $("trace").append(row);
  }
  text("trace-empty", r?.tool_trace?.length ? "" : "任务结束后显示实际调用。");
  text(
    "metrics",
    pretty({
      elapsed_ms: r?.elapsed_ms ?? null,
      model_calls: r?.model_calls ?? null,
      usage_reported_calls: r?.usage_reported_calls ?? null,
      usage: r && Object.keys(r.usage || {}).length ? r.usage : "接口未提供",
      timings_ms: r?.timings_ms || {},
    }),
  );
  text("raw-result", r ? pretty(r) : "尚无结果");
}
function schedule() {
  clearTimeout(S.timer);
  if (++S.polls > 180) {
    notice("自动刷新已暂停，请手动刷新状态。");
    return;
  }
  S.timer = setTimeout(async () => {
    if (S.busy) {
      schedule();
      return;
    }
    try {
      await refresh();
    } catch (e) {
      notice(e.message, true);
    }
  }, 2000);
}
function showOp(op) {
  S.op = op;
  $("approval").hidden = false;
  text(
    "operation-title",
    `${op.kind === "publish_comment" ? "发布评论" : "添加已有标签"} → ${op.repository} #${op.issue_number}`,
  );
  text(
    "operation-state",
    `状态：${names[op.status]} · 已发送 ${op.attempts} 次`,
  );
  text(
    "operation-meta",
    `操作 ${op.operation_id}\n确认有效至 ${new Date(op.expires_at).toLocaleString()}\n内容 hash ${op.content_hash}`,
  );
  text("operation-content", op.payload.body ?? pretty(op.payload));
  text("operation-error", messages[op.error_code] || op.error_code || "");
  text("expected-text", op.confirmation_text);
  $("reviewed").checked = false;
  $("confirmation-text").value = "";
  $("comment-id").value = "";
  $("operation-link").hidden = true;
  if (op.result?.comment_url)
    link($("operation-link"), op.result.comment_url, "查看 GitHub 评论 ↗");
  text(
    "operation-result",
    pretty({
      result: op.result,
      timings_ms: op.timings_ms || {},
      events: op.events,
    }),
  );
  controls();
  if (op.status === "executing") schedule();
}
async function start() {
  const s = S.s;
  if (dirty()) throw Error("请先保存草稿。");
  let pending;
  try {
    pending = JSON.parse(
      sessionStorage.getItem("issue-assistant-pending") || "null",
    );
  } catch {}
  if (
    !pending ||
    pending.sid !== s.session_id ||
    pending.revision !== s.revision
  )
    pending = {
      sid: s.session_id,
      revision: s.revision,
      key: crypto.randomUUID(),
    };
  sessionStorage.setItem("issue-assistant-pending", pretty(pending));
  await api(`/sessions/${s.session_id}/tasks`, "POST", {
    expected_revision: pending.revision,
    request_key: pending.key,
  });
  sessionStorage.removeItem("issue-assistant-pending");
  S.polls = 0;
  await refresh();
  notice("分析已提交，可以查看结果或取消。");
}
$("create-form").onsubmit = (e) => {
  e.preventDefault();
  action(async () => {
    if (dirty()) throw Error("请先保存当前草稿。");
    const s = await api("/sessions", "POST", {
      issue_url: $("issue-url").value.trim(),
      use_knowledge: $("use-knowledge").checked,
    });
    await open(s.session_id);
    await start();
  });
};
$("refresh-list").onclick = () => action(listing);
$("next").onclick = () =>
  action(async () => {
    S.offset += 20;
    await listing();
  });
$("previous").onclick = () =>
  action(async () => {
    S.offset = Math.max(0, S.offset - 20);
    await listing();
  });
$("restore").onclick = () => action(() => open($("restore-id").value.trim()));
$("refresh").onclick = () => action(refresh);
$("analyze-again").onclick = () => action(start);
$("cancel-task").onclick = () =>
  action(async () => {
    const s = S.s;
    await api(
      `/sessions/${s.session_id}/tasks/${s.active_task_id}/cancel`,
      "POST",
    );
    await refresh();
    notice("分析已取消。");
  });
$("draft").oninput = () => {
  $("reviewed").checked = false;
  $("confirmation-text").value = "";
  controls();
};
$("save-draft").onclick = () =>
  action(async () => {
    const s = S.s;
    S.s = await api(`/sessions/${s.session_id}/draft`, "PATCH", {
      expected_revision: s.revision,
      text: $("draft").value,
    });
    await refresh();
    notice("草稿已保存；旧预览和确认已失效。");
  });
$("add-supplement").onclick = () =>
  action(async () => {
    if (dirty()) throw Error("请先保存草稿。");
    const s = S.s;
    S.s = await api(`/sessions/${s.session_id}/supplements`, "POST", {
      expected_revision: s.revision,
      text: $("supplement").value,
    });
    $("supplement").value = "";
    await refresh();
    notice("补充已保存，点击继续分析以使用这些信息。");
  });
async function preview(kind, labels = []) {
  if (dirty()) throw Error("请先保存草稿。");
  const s = S.s;
  showOp(
    await api(`/sessions/${s.session_id}/operations/preview`, "POST", {
      expected_revision: s.revision,
      kind,
      labels,
    }),
  );
  await refresh();
  notice("已生成本地预览，请审阅完整内容。");
}
$("preview-comment").onclick = () => action(() => preview("publish_comment"));
$("load-labels").onclick = () =>
  action(async () => {
    const data = await api(`/sessions/${S.s.session_id}/available-labels`);
    $("labels").replaceChildren();
    for (const name of data.labels) {
      const o = document.createElement("option");
      o.value = name;
      o.textContent = name;
      $("labels").append(o);
    }
    $("label-panel").hidden = false;
    notice(data.possibly_more ? "标签清单达到读取上限。" : "已有标签已读取。");
  });
$("preview-labels").onclick = () =>
  action(() =>
    preview(
      "add_labels",
      Array.from($("labels").selectedOptions).map((o) => o.value),
    ),
  );
$("reviewed").onchange = controls;
$("confirmation-text").oninput = controls;
$("confirm-execute").onclick = () =>
  action(async () => {
    const s = S.s,
      op = S.op;
    if (
      dirty() ||
      !$("reviewed").checked ||
      $("confirmation-text").value !== op.confirmation_text
    )
      throw Error("请重新核对完整内容。");
    const body = {
      content_hash: op.content_hash,
      confirmation_text: $("confirmation-text").value,
    };
    if (op.status === "failed") body.retry_after_attempt = op.attempts;
    const confirmed = await api(
      `/sessions/${s.session_id}/operations/${op.operation_id}/confirm`,
      "POST",
      body,
    );
    if (confirmed.status !== "confirmed")
      throw Error("操作状态已变化，请刷新。");
    showOp(
      await api(
        `/sessions/${s.session_id}/operations/${op.operation_id}/execute`,
        "POST",
      ),
    );
    S.polls = 0;
    await refresh();
    notice("已提交执行；连接中断时请查询原操作。");
  });
$("cancel-operation").onclick = () =>
  action(async () => {
    showOp(
      await api(
        `/sessions/${S.s.session_id}/operations/${S.op.operation_id}/cancel`,
        "POST",
      ),
    );
    await refresh();
  });
$("refresh-operation").onclick = () =>
  action(async () =>
    showOp(
      await api(`/sessions/${S.s.session_id}/operations/${S.op.operation_id}`),
    ),
  );
$("reconcile").onclick = () =>
  action(async () => {
    const body = {};
    if ($("comment-id").value) body.comment_id = Number($("comment-id").value);
    showOp(
      await api(
        `/sessions/${S.s.session_id}/operations/${S.op.operation_id}/reconcile`,
        "POST",
        body,
      ),
    );
    await refresh();
    notice(
      S.op.status === "unknown"
        ? "尚未找到足够证据，保留未知状态，不能重发。"
        : "只读核对完成。",
    );
  });
window.addEventListener("beforeunload", (e) => {
  if (dirty()) {
    e.preventDefault();
    e.returnValue = "";
  }
});
(async () => {
  try {
    S.health = await api("/health");
    const ready = await fetch("/ready").then((r) => r.json());
    text(
      "health",
      `${S.health.version} · ${ready.status === "ready" ? "配置就绪" : "配置待完成"}`,
    );
    text("repository", `允许仓库：${S.health.allowed_repository}`);
    $("demo").hidden = S.health.mode !== "offline_demo";
    text(
      "write-config",
      S.health.github_writes_enabled && S.health.github_token_configured
        ? "写入已配置，每条操作仍需核对完整内容并确认。"
        : "写入未启用或 token 未配置，可先分析和预览。",
    );
    if (!S.health.knowledge_enabled) {
      $("use-knowledge").checked = false;
      $("use-knowledge").disabled = true;
    }
    const sid = sessionStorage.getItem("issue-assistant-session");
    if (sid) {
      try {
        await open(sid);
      } catch {
        sessionStorage.removeItem("issue-assistant-session");
        await listing();
      }
    } else await listing();
    controls();
  } catch (e) {
    notice(e.message, true);
  }
})();
