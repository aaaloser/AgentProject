"use strict";

const elements = {
  dashboardStatus: document.getElementById("dashboard-status"),
  repoCount: document.getElementById("repo-count"),
  repoList: document.getElementById("repo-list"),
  repoContext: document.getElementById("repo-context"),
  commitStatus: document.getElementById("commit-status"),
  commitList: document.getElementById("commit-list"),
  commitCount: document.getElementById("commit-count"),
  detailPanel: document.getElementById("detail-panel"),
  headUpdate: document.getElementById("head-update"),
  refreshList: document.getElementById("refresh-list"),
  refreshHead: document.getElementById("refresh-head"),
  loadMore: document.getElementById("load-more"),
  taskPanel: document.getElementById("task-panel"),
  taskSelection: document.getElementById("task-selection"),
  taskScope: document.getElementById("task-scope"),
  taskDescription: document.getElementById("task-description"),
  taskVerificationCommands: document.getElementById("task-verification-commands"),
  taskPreview: document.getElementById("task-preview"),
  taskCreate: document.getElementById("task-create"),
  taskDemoRun: document.getElementById("task-demo-run"),
  taskDemoCancel: document.getElementById("task-demo-cancel"),
  taskRun: document.getElementById("task-run"),
  taskCancel: document.getElementById("task-cancel"),
  taskRunPolicy: document.getElementById("task-run-policy"),
  taskGate: document.getElementById("task-gate"),
  taskExplain: document.getElementById("task-explain"),
  taskStatus: document.getElementById("task-status"),
  taskPreviewResult: document.getElementById("task-preview-result"),
  taskSummary: document.getElementById("task-summary"),
  taskApprovals: document.getElementById("task-approvals"),
  taskFinalResult: document.getElementById("task-final-result"),
  taskEvents: document.getElementById("task-events"),
  localMode: document.getElementById("local-mode"),
};

const priorityLabels = {
  high: "高优先级",
  medium: "中优先级",
  low: "低优先级",
  manual_review: "需人工审查",
};
const priorityNotes = {
  high: "建议优先安排人工审查；这不表示已经发现缺陷。",
  medium: "建议按常规流程审查改动范围与引用。",
  low: "规则命中较少，仍需正常代码审查。",
  manual_review: "当前统计不足以机械判断，不能视为低风险。",
};
const limitationLabels = {
  ci_not_checked: "CI 检查结果未取得",
  tests_not_run: "测试执行结果未取得",
  shallow_boundary: "浅克隆边界：父提交或变更统计不可得",
};
const fileTypeLabels = {
  added: "A", modified: "M", deleted: "D", renamed: "R", copied: "C", type_changed: "T", unknown: "?",
};

const state = {
  repositories: [], repoId: null, anchorSha: null, currentHeadSha: null, selectedSha: null,
  commits: [], pinnedCommit: null, nextCursor: null, epoch: 0, detailEpoch: 0, pageController: null, detailController: null,
  taskEpoch: 0, taskRepoId: null, taskBaseSha: null, taskId: null, taskPreviewData: null,
  taskSequence: 0, taskBudgetUsageSeen: false, taskController: null, taskTimer: null, taskToken: null,
  demoAvailable: false, runAvailable: false, taskRunPolicy: null, taskIdempotency: null,
};

function node(tag, className = "", value = null) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (value !== null) item.textContent = String(value);
  return item;
}

function setStatus(target, message, isError = false) {
  target.textContent = message;
  target.classList.toggle("is-error", isError);
}

function shortSha(sha) { return sha ? sha.slice(0, 8) : "—"; }
function visibleText(value) {
  return String(value).replace(/[\u0000-\u001f\u007f]/g, (character) =>
    `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`);
}

function dateLabel(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date);
}

function currentRepository() { return state.repositories.find((item) => item.id === state.repoId) || null; }

function updateUrl(repoId, sha, taskId = null) {
  const url = new URL(window.location.href);
  if (repoId) url.searchParams.set("repo", repoId);
  else url.searchParams.delete("repo");
  if (sha) url.searchParams.set("sha", sha);
  else url.searchParams.delete("sha");
  if (taskId) url.searchParams.set("task", taskId);
  else url.searchParams.delete("task");
  url.searchParams.delete("anchor");
  window.history.replaceState(null, "", url);
}

async function requestJson(path, controller) {
  let timedOut = false;
  const timer = window.setTimeout(() => { timedOut = true; controller.abort(); }, 15000);
  try {
    const response = await fetch(path, {
      method: "GET", credentials: "omit", cache: "no-store", headers: { Accept: "application/json" }, signal: controller.signal,
    });
    if (!response.ok) {
      let payload = {};
      try { payload = await response.json(); } catch { /* Fixed fallback below. */ }
      const error = new Error("请求未完成");
      error.code = typeof payload.code === "string" ? payload.code : "request_error";
      throw error;
    }
    return await response.json();
  } catch (error) {
    if (timedOut) {
      const timeout = new Error("读取超时");
      timeout.code = "timeout";
      throw timeout;
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

function errorMessage(error, subject) {
  if (error.code === "timeout" || error.code === "git_timeout") return `${subject}超时，请稍后重试。`;
  if (error.code === "git_output_limit") return `${subject}内容过大，当前无法完整读取。`;
  if (error.code === "repository_unavailable") return "仓库当前不可用；请确认本地目录仍存在。";
  if (error.code === "commit_not_found") return "这条提交不在当前历史视图中。请刷新列表。";
  if (error.code === "invalid_cursor") return "分页已失效，请刷新当前仓库。";
  return `${subject}失败，请重试。`;
}

function showDetailPlaceholder(title, message) {
  const wrapper = node("div", "empty-detail");
  const art = node("div", "empty-art", "⌁");
  art.setAttribute("aria-hidden", "true");
  wrapper.append(art, node("h3", "", title), node("p", "", message));
  elements.detailPanel.replaceChildren(wrapper);
}

function showDetailError(message) {
  elements.detailPanel.replaceChildren(node("div", "detail-alert", message));
}

function renderRepositories() {
  elements.repoList.replaceChildren();
  elements.repoCount.textContent = String(state.repositories.length);
  for (const repository of state.repositories) {
    const button = node("button", "repo-card");
    button.type = "button";
    button.classList.toggle("is-selected", repository.id === state.repoId);
    button.setAttribute("aria-pressed", String(repository.id === state.repoId));
    button.setAttribute("aria-label", `仓库 ${repository.name}，${repository.branch || "detached HEAD"}`);
    const nameRow = node("span", "repo-name-row");
    const icon = node("span", "repo-icon", "⌂");
    icon.setAttribute("aria-hidden", "true");
    nameRow.append(icon, node("span", "repo-name", repository.name));
    const meta = node("span", "repo-meta");
    meta.append(node("span", "", repository.branch || "detached HEAD"));
    const dirty = node("span", `state-chip${repository.dirty ? " dirty" : ""}`, repository.dirty ? "未提交变更" : "工作树干净");
    meta.append(dirty);
    button.append(nameRow, meta, node("span", "repo-path", repository.path));
    button.addEventListener("click", () => { void selectRepository(repository.id); });
    elements.repoList.append(button);
  }
}

function renderRepositoryContext() {
  const repository = currentRepository();
  if (!repository) {
    elements.repoContext.textContent = "选择一个仓库，查看其提交。";
    return;
  }
  const name = node("span", "context-name", repository.name);
  const separator = node("span", "context-separator", "/");
  const branch = node("span", "", repository.branch || "detached HEAD");
  const sha = node("span", "context-sha", state.currentHeadSha ? `HEAD ${shortSha(state.currentHeadSha)}` : "暂无提交");
  elements.repoContext.replaceChildren(name, separator, branch, separator.cloneNode(true), sha);
}

function renderCommits() {
  elements.commitList.replaceChildren();
  const pinned = state.pinnedCommit && state.pinnedCommit.sha === state.selectedSha
    && !state.commits.some((item) => item.sha === state.pinnedCommit.sha);
  const visibleCommits = pinned ? [state.pinnedCommit, ...state.commits] : state.commits;
  for (const commit of visibleCommits) {
    const button = node("button", "commit-card");
    button.type = "button";
    button.classList.toggle("is-selected", commit.sha === state.selectedSha);
    button.setAttribute("aria-pressed", String(commit.sha === state.selectedSha));
    button.setAttribute("aria-label", `提交 ${shortSha(commit.sha)}，${commit.title}`);
    const meta = node("span", "commit-meta");
    meta.append(node("span", "commit-sha", shortSha(commit.sha)), node("span", "", dateLabel(commit.committed_at)));
    if (commit.parent_count > 1) meta.append(node("span", "", "合并提交"));
    if (pinned && commit.sha === state.pinnedCommit.sha) button.append(node("span", "pinned-note", "当前查看的历史提交 · 不在本页"));
    button.append(node("span", "commit-title", commit.title), meta);
    button.addEventListener("click", () => { void selectCommit(commit.sha); });
    elements.commitList.append(button);
  }
  elements.commitCount.textContent = state.commits.length ? `已显示 ${state.commits.length} 条` : "每页最多 50 条提交";
  elements.loadMore.hidden = !state.nextCursor;
  elements.loadMore.disabled = false;
}

function renderHeadUpdate() {
  elements.headUpdate.hidden = !state.anchorSha || !state.currentHeadSha || state.anchorSha === state.currentHeadSha;
}

async function loadPage(cursor, epoch, restoreSha = null) {
  if (!state.repoId) return;
  if (state.pageController) state.pageController.abort();
  const controller = new AbortController();
  state.pageController = controller;
  const repoId = state.repoId;
  const append = Boolean(cursor);
  elements.loadMore.disabled = true;
  setStatus(elements.commitStatus, append ? "正在加载更多提交…" : "正在读取提交历史…");
  const path = `/api/repositories/${encodeURIComponent(repoId)}/commits${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`;
  try {
    const page = await requestJson(path, controller);
    if (epoch !== state.epoch || repoId !== state.repoId) return;
    if (page.repo_id !== repoId || (append && page.anchor_sha !== state.anchorSha)) throw new Error("提交视图身份不匹配");
    state.anchorSha = page.anchor_sha;
    state.currentHeadSha = page.current_head_sha;
    state.nextCursor = page.next_cursor;
    const known = new Set(append ? state.commits.map((item) => item.sha) : []);
    state.commits = append ? state.commits : [];
    for (const item of page.commits) {
      if (!known.has(item.sha)) state.commits.push(item);
    }
    renderRepositoryContext();
    renderHeadUpdate();
    renderTaskSelection();
    renderCommits();
    elements.refreshList.disabled = false;
    setStatus(elements.commitStatus, state.commits.length ? "" : "这个仓库还没有提交。", false);
    if (!append) {
      const validRestore = typeof restoreSha === "string" && /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/i.test(restoreSha);
      if (state.anchorSha && validRestore) void selectCommit(restoreSha);
      else if (state.commits.length) void selectCommit(state.commits[0].sha);
      else showDetailPlaceholder("暂无提交", "此仓库还没有可审查的历史提交。");
    }
  } catch (error) {
    if (epoch !== state.epoch || controller.signal.aborted && error.code !== "timeout") return;
    setStatus(elements.commitStatus, errorMessage(error, "提交列表读取"), true);
    elements.loadMore.disabled = false;
    if (!append) showDetailPlaceholder("无法读取历史", "请刷新当前仓库，或稍后重试。");
  }
}

async function selectRepository(repoId, restoreSha = null) {
  if (!state.repositories.some((repository) => repository.id === repoId)) return;
  if (state.repoId !== repoId) {
    elements.taskScope.value = "";
    elements.taskDescription.value = "";
  }
  state.epoch += 1;
  state.detailEpoch += 1;
  if (state.pageController) state.pageController.abort();
  if (state.detailController) state.detailController.abort();
  state.repoId = repoId;
  state.anchorSha = null;
  state.currentHeadSha = null;
  state.selectedSha = null;
  resetTaskIdentity(repoId, null);
  state.commits = [];
  state.pinnedCommit = null;
  state.nextCursor = null;
  updateUrl(repoId, null);
  renderRepositories();
  renderRepositoryContext();
  renderCommits();
  renderHeadUpdate();
  elements.refreshList.disabled = true;
  showDetailPlaceholder("正在准备审查", "读取当前仓库的提交历史后显示详情。");
  await loadPage(null, state.epoch, restoreSha);
}

function appendSection(title, subtle = "") {
  const section = node("section", "detail-section");
  const heading = node("h3", "section-heading");
  heading.append(node("span", "", title));
  if (subtle) heading.append(node("span", "section-subtle", subtle));
  section.append(heading);
  return section;
}

function renderDetail(detail, assessment) {
  const panel = elements.detailPanel;
  panel.replaceChildren();
  panel.append(node("p", "detail-kicker", "COMMIT / 提交身份"));
  panel.append(node("h3", "detail-title", detail.title));
  panel.append(node("span", "full-sha", detail.sha));
  panel.append(node("div", "detail-date", `${dateLabel(detail.committed_at)} · ${detail.parent_shas.length} 个父提交`));

  const priority = node("div", `priority-box ${assessment.priority}`);
  priority.append(node("p", "priority-caption", "改动审查优先级（启发式）"));
  const priorityRow = node("div", "priority-row");
  priorityRow.append(node("span", "priority-label", priorityLabels[assessment.priority] || "需人工审查"));
  priorityRow.append(node("span", "priority-code", assessment.priority));
  priority.append(priorityRow, node("p", "priority-note", priorityNotes[assessment.priority] || priorityNotes.manual_review));
  panel.append(priority);

  const stats = appendSection("改动概览", "仅根据 Git 提交统计");
  const grid = node("div", "metric-grid");
  const metrics = [
    [assessment.signals.changed_files, "变更文件"],
    [assessment.signals.changed_lines ?? "—", "增删总行数"],
    [detail.parent_shas.length, "父提交"],
  ];
  for (const [value, label] of metrics) {
    const metric = node("div", "metric");
    metric.append(node("span", "metric-value", value), node("span", "metric-label", label));
    grid.append(metric);
  }
  stats.append(grid);
  panel.append(stats);

  const reasons = appendSection("判定依据", `${assessment.reasons.length} 条规则命中`);
  if (assessment.reasons.length) {
    const list = node("ul", "reason-list");
    for (const reason of assessment.reasons) {
      const item = node("li");
      const dot = node("span", "reason-dot");
      dot.setAttribute("aria-hidden", "true");
      item.append(dot, node("span", "", reason.message));
      list.append(item);
    }
    reasons.append(list);
  } else reasons.append(node("p", "muted-line", "未命中额外优先规则；仍需正常人工审查。"));
  panel.append(reasons);

  const limits = appendSection("信息缺口", "未取得 ≠ 检查失败");
  const limitList = node("ul", "limitation-list");
  for (const code of assessment.limitations) {
    const item = node("li");
    const dot = node("span", "limit-dot", "○");
    dot.setAttribute("aria-hidden", "true");
    item.append(dot, node("span", "", limitationLabels[code] || code));
    limitList.append(item);
  }
  limits.append(limitList);
  if (detail.stats_unavailable_reason) limits.append(node("p", "muted-line", `统计不可用：${limitationLabels[detail.stats_unavailable_reason] || detail.stats_unavailable_reason}`));
  panel.append(limits);

  const files = appendSection("变更文件", `${detail.files.length} 个文件`);
  if (detail.files.length) {
    const list = node("ul", "file-list");
    for (const file of detail.files) {
      const item = node("li", "file-row");
      const paths = node("span", "file-paths", file.path);
      if (file.previous_path) paths.append(node("span", "file-previous", `原路径：${file.previous_path}`));
      const stat = node("span", "file-stat");
      stat.append(node("span", "stat-add", file.additions === null ? "+—" : `+${file.additions}`));
      stat.append(document.createTextNode(" / "));
      stat.append(node("span", "stat-del", file.deletions === null ? "−—" : `−${file.deletions}`));
      item.append(node("span", "file-type", fileTypeLabels[file.change_type] || "?"), paths, stat);
      list.append(item);
    }
    files.append(list);
  } else files.append(node("p", "muted-line", assessment.priority === "manual_review" ? "当前提交的文件统计不可用于机械判断。" : "没有可显示的文件变更。"));
  panel.append(files, node("div", "rule-version", `规则版本 · ${assessment.rule_version}`));
}

async function selectCommit(sha) {
  if (!state.repoId || !state.anchorSha || !/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/i.test(sha)) return;
  sha = sha.toLowerCase();
  if (state.detailController) state.detailController.abort();
  const controller = new AbortController();
  state.detailController = controller;
  state.detailEpoch += 1;
  const detailEpoch = state.detailEpoch;
  const epoch = state.epoch;
  const repoId = state.repoId;
  const anchorSha = state.anchorSha;
  state.selectedSha = sha;
  resetTaskIdentity(repoId, sha);
  updateUrl(repoId, sha);
  renderCommits();
  showDetailPlaceholder("正在读取提交", `正在分析 ${shortSha(sha)} 的改动统计…`);
  const path = `/api/repositories/${encodeURIComponent(repoId)}/commits/${encodeURIComponent(sha)}?anchor=${encodeURIComponent(anchorSha)}`;
  try {
    const result = await requestJson(path, controller);
    if (epoch !== state.epoch || detailEpoch !== state.detailEpoch || repoId !== state.repoId || sha !== state.selectedSha) return;
    if (result.repo_id !== repoId || result.anchor_sha !== anchorSha || result.detail.sha !== sha || result.assessment.sha !== sha) {
      throw new Error("审查身份不匹配");
    }
    if (!state.commits.some((item) => item.sha === sha)) {
      state.pinnedCommit = {
        sha: result.detail.sha, title: result.detail.title,
        committed_at: result.detail.committed_at, parent_count: result.detail.parent_shas.length,
      };
      renderCommits();
    }
    renderDetail(result.detail, result.assessment);
  } catch (error) {
    if (epoch !== state.epoch || detailEpoch !== state.detailEpoch || controller.signal.aborted && error.code !== "timeout") return;
    showDetailError(errorMessage(error, "提交详情读取"));
  }
}

const taskStateLabels = {
  draft: "草稿", preparing: "正在准备副本", prepared: "副本已准备", running: "运行中",
  awaiting_approval: "命令等待审批", verifying: "验证阶段", stopping: "正在收束",
  cancelling: "正在停止", completed: "任务完成", failed: "任务失败",
  cancelled: "任务已取消", timed_out: "超时", interrupted: "已中断", cleanup_failed: "清理失败 · 禁止新任务",
};
const blockerLabels = {
  unsafe_path: "不安全路径", case_collision: "大小写路径冲突", excluded_path: "隐私或证据路径已排除",
  symlink: "符号链接", gitlink: "嵌套 Git 仓库", non_regular: "不是普通文件",
  file_too_large: "单文件超限", too_many_files: "文件数量超限", total_too_large: "总字节数超限",
};

function renderTaskSelection() {
  if (!state.taskRepoId || !state.taskBaseSha || state.taskRepoId !== state.repoId) {
    elements.taskSelection.textContent = "先选择仓库和提交。";
    return;
  }
  const repository = currentRepository();
  elements.taskSelection.replaceChildren(
    node("p", "", `仓库：${repository?.name || "已选仓库"}`),
    node("p", "", `固定提交完整 SHA：${state.taskBaseSha}`),
    node("p", "", `历史锚完整 SHA：${state.anchorSha || "未知"}`),
    node("p", "", `当前 HEAD 完整 SHA：${state.currentHeadSha || "未知"}`),
  );
  if (repository?.dirty) elements.taskSelection.append(node("p", "task-warning", "来源工作树含未提交改动；任务只使用上方固定提交。"));
}

function resetTaskIdentity(repoId, sha) {
  state.taskEpoch += 1;
  if (state.taskController) state.taskController.abort();
  if (state.taskTimer) window.clearTimeout(state.taskTimer);
  state.taskRepoId = repoId;
  state.taskBaseSha = sha;
  state.taskId = null;
  state.taskPreviewData = null;
  state.taskIdempotency = null;
  state.taskRunPolicy = null;
  state.taskSequence = 0;
  state.taskBudgetUsageSeen = false;
  elements.taskPreviewResult.replaceChildren();
  elements.taskSummary.replaceChildren();
  elements.taskRunPolicy.replaceChildren();
  elements.taskApprovals.replaceChildren();
  elements.taskFinalResult.replaceChildren();
  elements.taskEvents.replaceChildren();
  setStatus(elements.taskStatus, "");
  renderTaskSelection();
  elements.taskPreview.disabled = !repoId || !sha;
  elements.taskCreate.disabled = true;
  elements.taskDemoRun.disabled = true;
  elements.taskDemoCancel.disabled = true;
  elements.taskRun.disabled = true;
  elements.taskCancel.disabled = true;
}

async function postTask(path, payload, extraHeaders = {}) {
  const controller = new AbortController();
  state.taskController = controller;
  const timer = window.setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(path, {
      method: "POST", credentials: "omit", cache: "no-store", signal: controller.signal,
      headers: { "Content-Type": "application/json", "X-MokioClaw-CSRF": state.taskToken, ...extraHeaders },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(`任务请求失败：${response.status}`);
    return await response.json();
  } finally {
    window.clearTimeout(timer);
  }
}

function taskScope() {
  return elements.taskScope.value.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
}

async function previewTask() {
  const epoch = state.taskEpoch;
  const repoId = state.taskRepoId;
  const sha = state.taskBaseSha;
  const anchor = state.anchorSha;
  if (!repoId || !sha || !anchor || !state.taskToken) return;
  elements.taskCreate.disabled = true;
  elements.taskPreviewResult.replaceChildren();
  setStatus(elements.taskStatus, "正在预览固定提交范围…");
  try {
    const result = await postTask("/api/task-previews", {
      repo_id: repoId, base_sha: sha, anchor_sha: anchor, source_read_scope: taskScope(),
    });
    if (epoch !== state.taskEpoch || repoId !== state.repoId || sha !== state.selectedSha) return;
    state.taskPreviewData = result;
    state.taskIdempotency = window.crypto.randomUUID();
    const summary = node("p", "", `${result.file_count} 个文件 · ${result.total_bytes} 字节 · 10 分钟有效`);
    elements.taskPreviewResult.replaceChildren(summary);
    if (result.blocked_paths.length) {
      elements.taskPreviewResult.append(node("p", "task-warning", "所选范围含不支持的文件，请调整范围后重试。"));
      const blockers = node("ul", "task-blockers");
      for (const blocker of result.blocked_paths) {
        blockers.append(node("li", "", `${visibleText(blocker.path || "所选范围")} · ${blockerLabels[blocker.reason] || visibleText(blocker.reason)}`));
      }
      elements.taskPreviewResult.append(blockers);
      setStatus(elements.taskStatus, "预览存在阻断项。", true);
    } else {
      elements.taskCreate.disabled = false;
      setStatus(elements.taskStatus, "预览已确认；可准备独立副本。", false);
    }
  } catch {
    if (epoch === state.taskEpoch) setStatus(elements.taskStatus, "预览失败，请核对提交与相对路径。", true);
  }
}

function taskNumber(id) { return Number(document.getElementById(id).value); }
function verificationCommands() {
  return elements.taskVerificationCommands.value.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
}

async function createTask() {
  const preview = state.taskPreviewData;
  const idempotencyKey = state.taskIdempotency;
  if (!preview || !idempotencyKey || !state.taskToken) return;
  resetTaskIdentity(state.repoId, state.selectedSha);
  updateUrl(state.repoId, state.selectedSha);
  const epoch = state.taskEpoch;
  elements.taskCreate.disabled = true;
  setStatus(elements.taskStatus, "正在建立任务记录…");
  try {
    const record = await postTask("/api/tasks", {
      preview_id: preview.preview_id, repo_id: preview.repo_id, base_sha: preview.base_sha,
      anchor_sha: preview.anchor_sha, source_read_scope: taskScope(),
      description: elements.taskDescription.value, max_seconds: taskNumber("task-max-seconds"),
      max_attempts: taskNumber("task-max-attempts"), verification_commands: verificationCommands(),
      max_provider_calls: taskNumber("task-max-calls"), max_total_tokens: taskNumber("task-max-tokens"),
      max_output_tokens_per_call: taskNumber("task-output-tokens"),
    }, { "Idempotency-Key": idempotencyKey });
    if (epoch !== state.taskEpoch || record.repo_id !== state.repoId
      || record.base_sha !== state.selectedSha || record.anchor_sha !== state.anchorSha) return;
    state.taskId = record.task_id;
    updateUrl(state.repoId, state.selectedSha, record.task_id);
    renderTaskRecord(record);
    void pollTask(epoch);
  } catch {
    if (epoch === state.taskEpoch) {
      state.taskPreviewData = preview;
      state.taskIdempotency = idempotencyKey;
      elements.taskCreate.disabled = false;
      setStatus(elements.taskStatus, "任务创建结果未确认；请先核对任务状态，再用原请求重试。", true);
    }
  }
}

function renderTaskRecord(record) {
  const label = taskStateLabels[record.state] || "状态未知";
  elements.taskSummary.replaceChildren(node("p", "", `任务 ${record.task_id} · ${label}`));
  elements.taskDemoRun.disabled = !state.demoAvailable || record.state !== "prepared";
  elements.taskDemoCancel.disabled = !state.demoAvailable || !["running", "awaiting_approval", "verifying"].includes(record.state);
  elements.taskRun.disabled = !state.runAvailable || !state.taskRunPolicy || record.state !== "prepared";
  elements.taskCancel.disabled = !state.runAvailable || !["running", "awaiting_approval", "verifying"].includes(record.state);
  setStatus(elements.taskStatus, label, ["failed", "cleanup_failed"].includes(record.state));
}

function renderRunPolicy(policy) {
  const panel = elements.taskRunPolicy;
  panel.replaceChildren(node("h3", "", "真实运行前核对固定清单"));
  panel.append(
    node("p", "", `任务 ${policy.task_id} · 仓库 ${policy.repo_id}`),
    node("p", "", `固定提交 ${policy.base_sha} · 历史锚 ${policy.anchor_sha}`),
    node("p", "", `任务说明：${visibleText(policy.description)}`),
    node("p", "", `读取范围：${policy.source_read_scope.map(visibleText).join("、") || "无"}`),
    node("p", "", `写入范围：${policy.source_write_scope.map(visibleText).join("、") || "无"} · 暂存范围：${visibleText(policy.task_scratch_scope)}`),
    node("p", "", `模型 ${visibleText(policy.model)} · 镜像 ${policy.image_digest} · 容器网络 ${policy.network}`),
    node("p", "", `限额：${policy.max_seconds} 秒、${policy.max_attempts} 次尝试、${policy.max_provider_calls} 次 provider 请求、${policy.max_total_tokens} token、单次输出 ${policy.max_output_tokens_per_call} token`),
  );
  const commands = node("ol");
  for (const command of policy.verification_commands) commands.append(node("li", "", visibleText(command)));
  panel.append(node("h4", "", "固定验证命令（每条仍需单独批准）"), commands);
}

async function loadRunPolicy(epoch, taskId) {
  if (!state.runAvailable || state.taskRunPolicy) return;
  const policy = await requestJson(`/api/tasks/${encodeURIComponent(taskId)}/run-policy`, new AbortController());
  if (epoch !== state.taskEpoch || taskId !== state.taskId || policy.task_id !== taskId
    || policy.repo_id !== state.repoId || policy.base_sha !== state.taskBaseSha
    || policy.anchor_sha !== state.anchorSha) return;
  state.taskRunPolicy = policy;
  renderRunPolicy(policy);
  elements.taskRun.disabled = false;
}

function renderTaskEvents(events) {
  for (const event of events) {
    if (event.sequence <= state.taskSequence || event.task_id !== state.taskId) continue;
    state.taskSequence = event.sequence;
    let label = event.kind;
    if (event.kind === "state") label = taskStateLabels[event.data.state] || "状态更新";
    else if (event.kind === "stage") label = `阶段：${event.data.phase}`;
    else if (event.kind === "budget_usage") {
      state.taskBudgetUsageSeen = true;
      const stages = [
        ["entry", "入口"], ["chat", "聊天"], ["planner", "规划"],
        ["code_agent", "CodeAgent"], ["verifier", "验证"], ["context_compressor", "上下文压缩"],
      ];
      label = `已报告用量（本任务累计）：${stages.map(([key, name]) =>
        `${name} ${event.data[`${key}_calls`]} 次 / ${event.data[`${key}_reported_tokens`]} token`).join("；")}`;
    }
    else if (event.kind === "verification") label = `验证：${event.data.status}`;
    else if (event.kind === "tool_failure") label = `工具失败：${visibleText(event.data.tool)} · ${visibleText(event.data.category)}`;
    else if (event.kind === "approval_request") label = "命令等待审批";
    else if (event.kind === "approval_decision") label = `审批：${event.data.decision}`;
    elements.taskEvents.append(node("li", "", `${event.sequence} · ${label}`));
  }
}

function renderTaskResult(result) {
  const panel = elements.taskFinalResult;
  panel.replaceChildren(node("h3", "", "任务结果"));
  panel.append(node("p", "", `任务：${result.status} · 验证：${result.verification_status} · 固定提交：${shortSha(result.base_sha)}`));
  if (result.failure_kind) panel.append(node("p", "task-warning", `失败类别：${result.failure_kind}`));
  if (!state.taskBudgetUsageSeen) panel.append(node("p", "task-warning", "阶段模型用量未知：未收到脱敏汇总。"));
  panel.append(node("p", "", `补丁：${result.patch_summary.status} · ${result.patch_summary.changed_files} 个文件 · +${result.patch_summary.added_lines} / -${result.patch_summary.deleted_lines}`));
  if (result.patch_summary.reason) panel.append(node("p", "task-warning", `补丁限制：${result.patch_summary.reason}`));
  if (result.changed_files.length) {
    const files = node("ul");
    for (const file of result.changed_files) files.append(node("li", "", file));
    panel.append(files);
  }
  if (result.verification_results.length) {
    panel.append(node("h4", "", "固定命令验证"));
    const checks = node("ol");
    for (const check of result.verification_results) {
      checks.append(node("li", "", `第 ${check.attempt_id} 次 · ${visibleText(check.command)} · ${check.status} · 审批 ${check.command_request_id || "无"} · 退出码 ${check.exit_code ?? "无"} · ${check.duration_ms ?? "无"} ms · 输出未展示${check.output_truncated ? "，原始输出已截断" : ""}`));
    }
    panel.append(checks);
  }
  if (result.limitations.length) panel.append(node("p", "task-warning", `限制：${result.limitations.join("、")}`));
}

async function decideTaskApproval(approval, approved) {
  if (!state.taskId) return;
  try {
    await postTask(`/api/tasks/${encodeURIComponent(state.taskId)}/approvals/${encodeURIComponent(approval.command_request_id)}`, {
      attempt_id: approval.attempt_id, execution_digest: approval.execution_digest, approved,
    });
    elements.taskApprovals.replaceChildren();
    void pollTask(state.taskEpoch);
  } catch {
    setStatus(elements.taskStatus, "审批请求已失效，请刷新任务状态。", true);
  }
}

function renderTaskApprovals(approvals) {
  const panel = elements.taskApprovals;
  panel.replaceChildren();
  for (const approval of approvals) {
    const box = node("section", "task-approval");
    box.append(node("h3", "", `第 ${approval.attempt_id} 次尝试 · 待审批命令`));
    box.append(node("pre", "", visibleText(approval.command)));
    box.append(node("p", "", `目录 ${approval.cwd} · 超时 ${approval.timeout_seconds} 秒 · 镜像 ${approval.image_digest} · 网络 ${approval.network}`));
    const approve = node("button", "", "批准这一次执行");
    const deny = node("button", "", "拒绝");
    approve.type = "button"; deny.type = "button";
    approve.addEventListener("click", () => { approve.disabled = true; deny.disabled = true; void decideTaskApproval(approval, true); });
    deny.addEventListener("click", () => { approve.disabled = true; deny.disabled = true; void decideTaskApproval(approval, false); });
    box.append(approve, deny);
    panel.append(box);
  }
}

async function pollTask(epoch) {
  const taskId = state.taskId;
  const repoId = state.taskRepoId;
  const sha = state.taskBaseSha;
  if (!taskId) return;
  try {
    const record = await requestJson(`/api/tasks/${encodeURIComponent(taskId)}`, new AbortController());
    if (epoch !== state.taskEpoch || taskId !== state.taskId || repoId !== state.repoId || sha !== state.selectedSha
      || record.task_id !== taskId || record.repo_id !== repoId || record.base_sha !== sha) return;
    renderTaskRecord(record);
    if (record.state === "prepared") await loadRunPolicy(epoch, taskId);
    const result = await requestJson(`/api/tasks/${encodeURIComponent(taskId)}/events?after=${state.taskSequence}`, new AbortController());
    if (epoch !== state.taskEpoch || taskId !== state.taskId || result.task_id !== taskId) return;
    renderTaskEvents(result.events);
    if (record.state === "awaiting_approval") {
      const pending = await requestJson(`/api/tasks/${encodeURIComponent(taskId)}/approvals`, new AbortController());
      if (epoch !== state.taskEpoch || taskId !== state.taskId) return;
      renderTaskApprovals(pending.approvals);
    } else elements.taskApprovals.replaceChildren();
    if (record.state === "cleanup_failed") {
      elements.taskFinalResult.replaceChildren(node("p", "task-warning", "执行资源清理尚未确认，结果暂不可用。"));
    } else if (["completed", "failed", "cancelled", "timed_out", "interrupted"].includes(record.state)) {
      const finalResult = await requestJson(`/api/tasks/${encodeURIComponent(taskId)}/result`, new AbortController());
      if (epoch !== state.taskEpoch || taskId !== state.taskId || finalResult.task_id !== taskId) return;
      renderTaskResult(finalResult);
    }
    if (result.events.length === 100 || !["completed", "failed", "cancelled", "timed_out", "interrupted", "cleanup_failed", "prepared"].includes(record.state)) {
      state.taskTimer = window.setTimeout(() => { void pollTask(epoch); }, 800);
    }
  } catch {
    if (epoch === state.taskEpoch) setStatus(elements.taskStatus, "任务状态读取失败，请稍后重试。", true);
  }
}

async function demoAction(action) {
  const taskId = state.taskId;
  const epoch = state.taskEpoch;
  if (!taskId || !state.demoAvailable) return;
  try {
    const record = await postTask(`/api/tasks/${encodeURIComponent(taskId)}/demo-${action}`, {});
    if (epoch !== state.taskEpoch || taskId !== state.taskId) return;
    renderTaskRecord(record);
    void pollTask(epoch);
  } catch {
    if (epoch === state.taskEpoch) setStatus(elements.taskStatus, "演示操作未完成。", true);
  }
}

async function agentAction(action) {
  const taskId = state.taskId;
  const epoch = state.taskEpoch;
  if (!taskId || !state.runAvailable) return;
  if (action === "run") {
    const policy = state.taskRunPolicy;
    if (!policy || policy.task_id !== taskId || policy.base_sha !== state.taskBaseSha) return;
    if (!window.confirm(`运行固定任务 ${taskId}？\n提交 ${policy.base_sha}\n模型 ${policy.model}\n最多 ${policy.max_provider_calls} 次 provider 请求。命令仍逐条审批。`)) return;
    elements.taskRun.disabled = true;
  }
  try {
    const record = await postTask(`/api/tasks/${encodeURIComponent(taskId)}/${action}`, {});
    if (epoch !== state.taskEpoch || taskId !== state.taskId) return;
    renderTaskRecord(record);
    void pollTask(epoch);
  } catch {
    if (epoch === state.taskEpoch) setStatus(elements.taskStatus, "真实任务操作未完成；请刷新状态并核对运行门。", true);
  }
}

async function initializeTaskSession() {
  try {
    const session = await requestJson("/api/task-session", new AbortController());
    if (!session.task_available) return;
    state.taskToken = session.csrf_token;
    state.demoAvailable = session.demo_available === true;
    state.runAvailable = session.run_available === true;
    elements.taskDemoRun.hidden = !state.demoAvailable;
    elements.taskDemoCancel.hidden = !state.demoAvailable;
    elements.taskRun.hidden = !state.runAvailable;
    elements.taskCancel.hidden = !state.runAvailable;
    if (state.runAvailable) {
      elements.taskGate.textContent = "真实 Agent 可用 · 逐任务确认";
      elements.taskExplain.textContent = "固定提交建立隔离副本；先核对完整清单，再单独确认运行。每条命令需要另外审批。";
    }
    elements.taskPanel.hidden = false;
    elements.localMode.lastChild.textContent = "仅本机 · 来源只读";
    elements.taskPreview.disabled = !state.repoId || !state.selectedSha;
  } catch { /* Commit review stays usable when task support is unavailable. */ }
}

async function restoreTaskFromUrl(taskId) {
  if (!/^[A-Za-z0-9_-]{16,64}$/.test(taskId) || !state.taskToken
    || !state.repoId || !state.selectedSha || !state.anchorSha) return;
  const epoch = state.taskEpoch;
  const repoId = state.repoId;
  const sha = state.selectedSha;
  const anchor = state.anchorSha;
  try {
    const record = await requestJson(`/api/tasks/${encodeURIComponent(taskId)}`, new AbortController());
    if (epoch !== state.taskEpoch || repoId !== state.repoId || sha !== state.selectedSha) return;
    if (record.task_id !== taskId || record.repo_id !== repoId
      || record.base_sha !== sha || record.anchor_sha !== anchor) {
      setStatus(elements.taskStatus, "任务链接与所选仓库或提交不匹配。", true);
      return;
    }
    state.taskId = taskId;
    updateUrl(repoId, sha, taskId);
    renderTaskRecord(record);
    void pollTask(epoch);
  } catch {
    if (epoch === state.taskEpoch) setStatus(elements.taskStatus, "任务链接已失效，请重新准备任务。", true);
  }
}

async function initialize() {
  const params = new URL(window.location.href).searchParams;
  const requestedRepo = params.get("repo");
  const requestedSha = params.get("sha");
  const requestedTask = params.get("task");
  const sessionReady = initializeTaskSession();
  try {
    const repositories = await requestJson("/api/repositories", new AbortController());
    if (!Array.isArray(repositories)) throw new Error("仓库列表格式不正确");
    state.repositories = repositories;
    renderRepositories();
    setStatus(elements.dashboardStatus, repositories.length ? "" : "本次启动没有登记仓库。", false);
    if (!repositories.length) {
      setStatus(elements.commitStatus, "没有可浏览的仓库。");
      return;
    }
    const selected = repositories.find((item) => item.id === requestedRepo) || repositories[0];
    await selectRepository(selected.id, selected.id === requestedRepo ? requestedSha : null);
    if (requestedTask) {
      await sessionReady;
      await restoreTaskFromUrl(requestedTask);
    }
  } catch (error) {
    setStatus(elements.dashboardStatus, errorMessage(error, "仓库列表读取"), true);
    setStatus(elements.commitStatus, "仓库列表不可用。", true);
  }
}

elements.refreshList.addEventListener("click", () => { if (state.repoId) void selectRepository(state.repoId); });
elements.refreshHead.addEventListener("click", () => { if (state.repoId) void selectRepository(state.repoId); });
elements.loadMore.addEventListener("click", () => { if (state.nextCursor) void loadPage(state.nextCursor, state.epoch); });
elements.taskPreview.addEventListener("click", () => { void previewTask(); });
elements.taskCreate.addEventListener("click", () => { void createTask(); });
elements.taskDemoRun.addEventListener("click", () => { void demoAction("run"); });
elements.taskDemoCancel.addEventListener("click", () => { void demoAction("cancel"); });
elements.taskRun.addEventListener("click", () => { void agentAction("run"); });
elements.taskCancel.addEventListener("click", () => { void agentAction("cancel"); });
void initialize();
