"use strict";
let exampleItems = [],
  storageState = null;
function renderSource() {
  const item = exampleItems.find((x) => x.id === S.s?.example_id);
  $("source-note").hidden = !item;
  $("teaching-input").hidden = !item?.input_text;
  if (!item) {
    text(
      "write-config",
      S.health?.github_writes_enabled && S.health?.github_token_configured
        ? "写入已配置，每条操作仍需核对完整内容并确认。"
        : "写入未启用或 token 未配置，可先分析和预览。",
    );
    return;
  }
  const teaching = item.kind === "teaching_case";
  text(
    "source-note",
    teaching
      ? "离线教学案例：本地编写的固定结果，模型 / MCP / GitHub 调用均为0，不是真实GitHub Issue。"
      : "公开历史案例：实时只读分析，不使用GitHub token，不加载你自己的仓库知识库；已关闭也不代表回复是正确答案。",
  );
  text("teaching-input", item.input_text || "");
  if (teaching) {
    $("target").removeAttribute("href");
    text("target", "教学案例：" + item.title);
  }
  text(
    "write-config",
    "此案例始终只读，程序禁止发布评论和添加标签。编辑和保存仅用于本机练习。",
  );
}
function showStorage() {
  if (!storageState) return;
  const b = storageState;
  text(
    "storage-saved",
    dirty()
      ? "草稿有未保存修改"
      : S.s
        ? "业务数据已保存到本机"
        : "使用固定本机数据库",
  );
  const latest = b.last_backup_at
    ? new Date(b.last_backup_at).toLocaleString()
    : "尚无成功备份";
  const statuses = {
    running: "正在备份",
    pending: "等待合并备份",
    failed: "备份失败：已保存的数据仍在，请重试",
    not_created: "备份尚未生成",
    ok: "备份已完成",
  };
  text(
    "storage-backup",
    `${statuses[b.backup_status] || b.backup_status} · 最近成功备份：${latest}`,
  );
  $("storage-backup").classList.toggle("error", Boolean(b.backup_error));
  text(
    "storage-path",
    `数据文件：${b.database_path}\n备份目录：${b.backup_directory}\n自动备份最多保留 ${b.retention} 份，升级与恢复前的保护备份另存。`,
  );
  $("backup-now").disabled = !b.auto_backup_enabled;
  S.storageHold = b.writes_paused_after_restore;
  if (S.storageHold)
    text(
      "write-config",
      "当前数据从备份恢复，写入已暂停；请先核对GitHub写入历史，按恢复说明解除暂停。",
    );
  controls();
}
async function refreshStorage() {
  try {
    storageState = await api("/storage/status");
    showStorage();
  } catch {
    text(
      "storage-backup",
      "无法读取备份状态，请刷新检查；不能据此判断备份成功。",
    );
  }
}
document.addEventListener("session-rendered", () => {
  renderSource();
  showStorage();
});
$("draft").addEventListener("input", showStorage);
$("backup-now").onclick = () =>
  action(async () => {
    await api("/storage/backup", "POST");
    await refreshStorage();
    notice("已请求备份已保存的数据；未保存的编辑不在备份中。");
  });
$("example-picker").onchange = () => {
  const item = exampleItems.find((x) => x.id === $("example-picker").value);
  text(
    "example-description",
    item
      ? `${item.title}\n${item.description}`
      : "选择一个案例。公开案例会调用真实模型，教学案例是固定预编写结果。",
  );
};
$("open-example").onclick = () =>
  action(async () => {
    if (dirty()) throw Error("请先保存当前草稿。");
    const item = exampleItems.find((x) => x.id === $("example-picker").value);
    if (!item) throw Error("请先选择案例。");
    const s = await api("/sessions", "POST", {
      issue_url: item.issue_url,
      example_id: item.id,
      use_knowledge: false,
    });
    await open(s.session_id);
    await start();
    renderSource();
  });
(async () => {
  try {
    exampleItems = await api("/examples");
    for (const [kind, label] of [
      ["public_example", "真实公开案例（调用模型，仅限只读）"],
      ["teaching_case", "离线教学案例（无需密钥，固定结果）"],
    ]) {
      const group = document.createElement("optgroup");
      group.label = label;
      for (const item of exampleItems.filter((x) => x.kind === kind)) {
        const option = document.createElement("option");
        option.value = item.id;
        option.textContent = item.title;
        group.append(option);
      }
      $("example-picker").append(group);
    }
    renderSource();
  } catch {
    text(
      "example-description",
      "案例库加载失败，请检查本地cases/catalog.json。",
    );
  }
  await refreshStorage();
  setInterval(refreshStorage, 3000);
})();
