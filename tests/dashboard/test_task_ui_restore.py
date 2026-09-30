"""Exercise the shipped browser script with a small in-memory DOM."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


SCRIPT = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor(tag = 'div') {
    this.tag = tag;
    this.children = [];
    this.classList = { toggle() {} };
    this.value = '';
    this.textContent = '';
  }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  setAttribute() {}
  addEventListener() {}
  cloneNode() { return new Element(this.tag); }
  get lastChild() { return this.children.at(-1) || new Element(); }
}

async function scenario(taskRepo) {
  const taskId = 'task_1234567890123456';
  const nextId = 'task_abcdefghijklmnop';
  const sha = 'a'.repeat(40);
  const repo = 'repo_12345678';
  const elements = new Map();
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, new Element());
      return elements.get(id);
    },
    createElement(tag) { return new Element(tag); },
    createTextNode(text) { const item = new Element('text'); item.textContent = text; return item; },
  };
  document.getElementById('local-mode').append(new Element());
  const window = {
    location: { href: `http://127.0.0.1/?repo=${repo}&sha=${sha}&task=${taskId}` },
    history: { replaceState(_state, _title, url) { window.location.href = String(url); } },
    setTimeout() { return 1; }, clearTimeout() {},
  };
  const record = { task_id: taskId, repo_id: taskRepo, base_sha: sha,
    anchor_sha: sha, state: 'awaiting_approval', sequence: 1, attempt_id: 1,
    failure_kind: null, verification_status: 'not_run', created_at: '2026-09-29T00:00:00Z' };
  const nextRecord = { ...record, task_id: nextId, repo_id: repo, state: 'prepared',
    attempt_id: null, sequence: 0 };
  let completeCreate;
  const fetch = async (path) => {
    let body;
    if (path === '/api/task-session') body = { task_available: true,
      demo_available: false, run_available: true, csrf_token: 'token' };
    else if (path === '/api/repositories') body = [{ id: repo, name: 'MokioAgent',
      path: 'fixture', branch: 'main', dirty: false }];
    else if (path.endsWith('/commits')) body = { repo_id: repo, anchor_sha: sha,
      current_head_sha: sha, next_cursor: null, commits: [{ sha, title: 'fixture',
        committed_at: '2026-09-29T00:00:00Z', parent_count: 1 }] };
    else if (path.includes('/commits/')) body = { repo_id: repo, anchor_sha: sha,
      detail: { sha, title: 'fixture', committed_at: '2026-09-29T00:00:00Z',
        parent_shas: ['b'.repeat(40)], files: [] },
      assessment: { sha, priority: 'low', signals: { changed_files: 0,
        changed_lines: 0 }, reasons: [], limitations: [], rule_version: 'v1' } };
    else if (path === '/api/tasks') return new Promise(resolve => {
      completeCreate = () => resolve({ ok: true, json: async () => nextRecord });
    });
    else if (path === `/api/tasks/${taskId}`) body = record;
    else if (path === `/api/tasks/${nextId}`) body = nextRecord;
    else if (path === `/api/tasks/${nextId}/run-policy`) body = {
      task_id: nextId, repo_id: repo, base_sha: sha, anchor_sha: sha,
      description: 'new task', source_read_scope: ['src/'], source_write_scope: ['src/'],
      task_scratch_scope: '.mokioclaw/task-scratch/', model: 'fake',
      image_digest: 'sha256:' + 'a'.repeat(64), network: 'none', max_seconds: 60,
      max_attempts: 1, max_provider_calls: 1, max_total_tokens: 1000,
      max_output_tokens_per_call: 100, verification_commands: ['new-check'],
    };
    else if (path.startsWith(`/api/tasks/${taskId}/events`)) body = { task_id: taskId, events: [] };
    else if (path.startsWith(`/api/tasks/${nextId}/events`)) body = { task_id: nextId, events: [] };
    else if (path === `/api/tasks/${taskId}/approvals`) body = { task_id: taskId,
      approvals: [{ task_id: taskId, attempt_id: 1, command_request_id: 'request_1234567890123456',
        execution_digest: 'f'.repeat(64), command: 'ls -la', cwd: '/workspace',
        timeout_seconds: 120, image_digest: 'sha256:' + 'a'.repeat(64), network: 'none' }] };
    else throw new Error(`Unexpected request: ${path}`);
    return { ok: true, json: async () => body };
  };
  const context = vm.createContext({ document, window, fetch, URL, AbortController,
    Intl, Date, Number, String, Set, console });
  vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
  for (let i = 0; i < 30; i += 1) await new Promise(setImmediate);
  return { context, elements, window, taskId, nextId, completeCreate: () => completeCreate() };
}

(async () => {
  const good = await scenario('repo_12345678');
  const sha = 'a'.repeat(40);
  assert.equal(vm.runInContext('state.taskId', good.context), good.taskId);
  assert.equal(good.elements.get('task-approvals').children.length, 1);
  assert.match(good.window.location.href, /[?&]task=task_1234567890123456/);
  vm.runInContext(`renderTaskEvents([{task_id: '${good.taskId}', sequence: 1,
    kind: 'tool_failure', data: {tool: 'TodoWriteTool', category: 'invalid_arguments'}}])`, good.context);
  assert.match(good.elements.get('task-events').children[0].textContent,
    /TodoWriteTool.*invalid_arguments/);
  vm.runInContext(`renderTaskEvents([{task_id: '${good.taskId}', sequence: 2,
    kind: 'budget_usage', data: {
      entry_calls: 1, entry_reported_tokens: 5,
      chat_calls: 0, chat_reported_tokens: 0,
      planner_calls: 2, planner_reported_tokens: 9,
      code_agent_calls: 3, code_agent_reported_tokens: 30,
      verifier_calls: 0, verifier_reported_tokens: 0,
      context_compressor_calls: 0, context_compressor_reported_tokens: 0,
      secret: 'FAKE_PRIVATE_TOKEN'
    }}])`, good.context);
  const usageText = good.elements.get('task-events').children[1].textContent;
  assert.match(usageText, /入口.*1 次.*5 token.*规划.*2 次.*9 token.*CodeAgent.*3 次.*30 token/);
  assert.doesNotMatch(usageText, /FAKE_PRIVATE_TOKEN/);
  vm.runInContext(`const finalResult = {status: 'failed', verification_status: 'not_run',
    base_sha: '${sha}', failure_kind: 'provider_budget_exhausted',
    patch_summary: {status: 'patch_unavailable', changed_files: 0, added_lines: 0, deleted_lines: 0},
    changed_files: [], verification_results: [], limitations: []};
    renderTaskResult(finalResult)`, good.context);
  assert.equal(good.elements.get('task-final-result').children.some(item =>
    item.textContent.includes('用量未知')), false);
  vm.runInContext('state.taskBudgetUsageSeen = false; renderTaskResult(finalResult)', good.context);
  assert.equal(good.elements.get('task-final-result').children.some(item =>
    item.textContent.includes('用量未知')), true);
  const oldPolicy = good.elements.get('task-run-policy');
  const oldResult = good.elements.get('task-final-result');
  const oldEvents = good.elements.get('task-events');
  oldPolicy.append(new Element('old-policy'));
  oldResult.append(new Element('old-result'));
  oldEvents.append(new Element('old-event'));
  const taskId = good.taskId;
  const repo = 'repo_12345678';
  vm.runInContext(`state.taskRunPolicy = {task_id: '${taskId}', base_sha: '${sha}'};
    state.taskPreviewData = {preview_id: 'preview_12345678901234', repo_id: '${repo}',
      base_sha: '${sha}', anchor_sha: '${sha}'};
    state.taskIdempotency = 'create-next-task';
    state.taskSequence = 7;`, good.context);
  vm.runInContext('void createTask()', good.context);
  await new Promise(setImmediate);
  assert.equal(vm.runInContext('state.taskId', good.context), null);
  assert.equal(vm.runInContext('state.taskRunPolicy', good.context), null);
  assert.equal(vm.runInContext('state.taskSequence', good.context), 0);
  assert.equal(oldPolicy.children.length, 0);
  assert.equal(oldResult.children.length, 0);
  assert.equal(oldEvents.children.length, 0);
  assert.equal(good.elements.get('task-approvals').children.length, 0);
  assert.doesNotMatch(good.window.location.href, /[?&]task=/);
  good.completeCreate();
  for (let i = 0; i < 20; i += 1) await new Promise(setImmediate);
  assert.equal(vm.runInContext('state.taskId', good.context), good.nextId);
  assert.equal(vm.runInContext('state.taskRunPolicy.task_id', good.context), good.nextId);
  assert.match(good.window.location.href, /[?&]task=task_abcdefghijklmnop/);
  assert.equal(oldResult.children.length, 0);
  const bad = await scenario('repo_other1234');
  assert.equal(vm.runInContext('state.taskId', bad.context), null);
  assert.doesNotMatch(bad.window.location.href, /[?&]task=/);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_task_ui_keeps_restored_and_new_data_bound_to_selected_task() -> None:
    script = Path(__file__).parents[2] / "src" / "mokioclaw" / "dashboard" / "static" / "app.js"
    result = subprocess.run([shutil.which("node"), "-e", SCRIPT, str(script)],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
