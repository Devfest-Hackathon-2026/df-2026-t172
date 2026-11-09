import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import { changeTaskCategory, changeTaskDetails, changeTaskUrgency, completeTask, loadTaskCategories, loadTasks, reopenTask, taskCategory, taskPatients, visibleTasks } from "../js/tasks.js";
import { clearPatientData, getState, setLocalTaskAssignment, setTaskState } from "../js/state.js";

const originalFetch = globalThis.fetch;
const task = {
  id: "t_test", patient_id: "p302", room: "302", name: "架空患者", text: "タオルをもう1枚",
  patient_words: ["タオル、もう1枚もらえるかな"], urgency: "none", urgency_set_by: "rule", cue: null,
  status: "open", created_at: "2026-11-08T09:00:00+09:00", done_at: null,
};

beforeEach(() => {
  globalThis.window = Object.assign(new EventTarget(), {
    location: { origin: "http://localhost:8765" },
    sessionStorage: { getItem: () => "test-only-passcode", removeItem() {} },
  });
  clearPatientData();
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  delete globalThis.window;
});

test("dedicated task screen retrieves open and completed tasks with authentication", async () => {
  globalThis.fetch = async (url, options) => {
    assert.equal(url.pathname, "/api/tasks");
    assert.equal(url.searchParams.get("status"), "all");
    assert.equal(options.method, "GET");
    assert.equal(options.headers.get("X-Passcode"), "test-only-passcode");
    return Response.json({ mode: "mock", tasks: [task, { ...task, id: "t_done", status: "done" }] });
  };
  assert.deepEqual((await loadTasks()).map((t) => t.status), ["open", "done"]);
});

test("category choices are available locally without an additional API request", async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; throw new Error("Unexpected API request"); };
  const categories = await loadTaskCategories();
  assert.deepEqual(categories, [
    "物品", "食事", "排泄", "移動", "付き添い", "清潔", "着替え", "体調",
    "痛みの訴え", "医師への確認", "その他",
  ]);
  categories.splice(0);
  assert.equal((await loadTaskCategories()).length, 11);
  assert.equal(calls, 0);
});

test("category updates send only category and wait for the server without altering urgency or the original task", async () => {
  const original = { ...task, category: "物品", category_set_by: "ai", role: "看護助手" };
  let finish;
  globalThis.fetch = async (url, options) => {
    assert.equal(url.pathname, "/api/tasks/t_test");
    assert.equal(options.method, "PATCH");
    assert.deepEqual(JSON.parse(options.body), { category: "食事" });
    return new Promise((resolve) => { finish = resolve; });
  };
  const pending = changeTaskCategory(original, { category: "食事" });
  assert.equal(original.category, "物品");
  finish(Response.json({ mode: "mock", task: { ...original, category: "食事", category_set_by: "nurse" } }));
  const updated = await pending;
  assert.equal(updated.category, "食事");
  assert.equal(updated.category_set_by, "nurse");
  assert.equal(updated.urgency, original.urgency);
  assert.equal(updated.role, original.role);
  assert.equal(original.category, "物品");
  assert.equal(taskCategory(task), "その他");
});

test("urgency and category are saved together in one request without sending the local assignee", async () => {
  const original = { ...task, category: "物品", role: "看護師" };
  let finish, calls = 0;
  globalThis.fetch = async (url, options) => {
    calls += 1;
    assert.equal(url.pathname, "/api/tasks/t_test");
    assert.deepEqual(JSON.parse(options.body), { urgency: "timed", category: "食事" });
    return new Promise((resolve) => { finish = resolve; });
  };
  const pending = changeTaskDetails(original, { urgency: "timed", category: "食事" });
  assert.equal(original.category, "物品");
  assert.equal(original.urgency, "none");
  finish(Response.json({ mode: "mock", task: { ...original, urgency: "timed", category: "食事" } }));
  const updated = await pending;
  assert.equal(calls, 1);
  assert.equal(updated.category, "食事");
  assert.equal(updated.urgency, "timed");
  assert.equal(updated.role, original.role);
});

test("combined task updates reject invalid choices and partially applied server responses", async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return Response.json({ mode: "mock", task: { ...task, category: "物品", urgency: "timed" } });
  };
  assert.throws(() => changeTaskDetails(task), { code: "invalid_task_changes" });
  assert.throws(() => changeTaskDetails(task, { urgency: "invalid", category: "食事" }), { code: "invalid_urgency" });
  assert.throws(() => changeTaskDetails(task, { urgency: "timed", category: "" }), { code: "invalid_category" });
  assert.equal(calls, 0);
  await assert.rejects(changeTaskDetails(task, { urgency: "timed", category: "食事" }), { code: "invalid_response" });
  assert.equal(calls, 1);
  assert.equal(task.urgency, "none");
});

test("failed category updates keep the original category, and unchanged server responses are rejected", async () => {
  const original = { ...task, category: "物品" };
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return Response.json({ mode: "mock", error: { code: "save_failed", message: "保存できませんでした" } }, { status: 500 });
  };
  await assert.rejects(changeTaskCategory(original, { category: "食事" }), { status: 500 });
  assert.equal(calls, 1);
  assert.equal(original.category, "物品");
  globalThis.fetch = async () => Response.json({ mode: "mock", task: original });
  await assert.rejects(changeTaskCategory(original, { category: "食事" }), { code: "invalid_response" });
  assert.throws(() => changeTaskCategory(original), { code: "invalid_category" });
  assert.throws(() => changeTaskCategory(original, { category: "" }), { code: "invalid_category" });
});

test("demo assignments stay separate from API tasks and survive task refreshes and completion", () => {
  globalThis.fetch = () => { throw new Error("demo assignments must not use the API"); };
  setTaskState({ tasks: [task], status: "ready" });
  assert.equal(setLocalTaskAssignment(task.id, "self"), true);
  assert.equal(getState().localTaskAssignments.get(task.id), "self");
  assert.equal(Object.hasOwn(getState().tasks[0], "assigned_to"), false);
  setTaskState({ tasks: [{ ...task }] });
  assert.equal(getState().localTaskAssignments.get(task.id), "self");
  assert.equal(setLocalTaskAssignment(task.id, "nurse_b"), true);
  const snapshot = getState().localTaskAssignments;
  snapshot.clear();
  assert.equal(getState().localTaskAssignments.get(task.id), "nurse_b");
  setTaskState({ tasks: [{ ...task, status: "done" }] });
  assert.equal(getState().localTaskAssignments.get(task.id), "nurse_b");
  assert.equal(setLocalTaskAssignment(task.id, "self"), false);
  setTaskState({ tasks: [task] });
  assert.equal(setLocalTaskAssignment(task.id, ""), true);
  assert.equal(getState().localTaskAssignments.has(task.id), false);
});

test("demo assignments reject unknown tasks, unknown nurses and pending updates and clear with patient data", () => {
  setTaskState({ tasks: [task], status: "ready" });
  assert.equal(setLocalTaskAssignment("missing", "self"), false);
  assert.equal(setLocalTaskAssignment(task.id, "unknown"), false);
  setTaskState({ pendingIds: [task.id] });
  assert.equal(setLocalTaskAssignment(task.id, "self"), false);
  setTaskState({ pendingIds: [] });
  assert.equal(setLocalTaskAssignment(task.id, "nurse_a"), true);
  clearPatientData();
  assert.equal(getState().localTaskAssignments.size, 0);
});

test("open tasks respect patient IDs, urgency and oldest-first ordering without altering the source", () => {
  const tasks = [
    { ...task, id: "t_other", patient_id: "p303", urgency: "said_urgent" },
    { ...task, id: "t_later", created_at: "2026-11-08T10:00:00+09:00" },
    { ...task, id: "t_urgent", urgency: "said_urgent" },
    { ...task, id: "t_timed", urgency: "timed" }, task,
    { ...task, id: "t_done", status: "done" },
  ];
  assert.deepEqual(visibleTasks(tasks, { patientId: "p302" }).map((t) => t.id), ["t_urgent", "t_timed", "t_test", "t_later"]);
  assert.equal(tasks[0].id, "t_other");
  assert.deepEqual(visibleTasks(tasks, { patientId: "none" }), []);
});

test("completed tasks show most recently completed first, independent of urgency", () => {
  const tasks = [
    { ...task, id: "t_early", status: "done", done_at: "2026-11-08T10:00:00+09:00", urgency: "said_urgent" },
    { ...task, id: "t_late", status: "done", done_at: "2026-11-08T11:00:00+09:00" }, task,
  ];
  assert.deepEqual(visibleTasks(tasks, { view: "done" }).map((t) => t.id), ["t_late", "t_early"]);
});

test("patient choices include completed tasks, sort rooms numerically and distinguish equal names", () => {
  const tasks = [
    { ...task, patient_id: "p10", room: "10" },
    { ...task, patient_id: "p2", room: "2", status: "done" },
    { ...task, id: "t_second", patient_id: "p10", room: "10" },
  ];
  assert.deepEqual(taskPatients(tasks).map((p) => p.id), ["p2", "p10"]);
});

test("completion sends only status done and waits for success before returning the new task", async () => {
  let finish;
  globalThis.fetch = async (url, options) => {
    assert.equal(url.pathname, "/api/tasks/t_test");
    assert.equal(options.method, "PATCH");
    assert.equal(options.headers.get("X-Passcode"), "test-only-passcode");
    assert.deepEqual(JSON.parse(options.body), { status: "done" });
    return new Promise((resolve) => { finish = resolve; });
  };
  const pending = completeTask(task);
  assert.equal(task.status, "open");
  finish(Response.json({ mode: "mock", task: { ...task, status: "done", done_at: "2026-11-08T12:00:00+09:00" } }));
  const updated = await pending;
  assert.equal(updated.status, "done");
  assert.equal(updated.done_at, "2026-11-08T12:00:00+09:00");
  assert.equal(task.status, "open");
});

test("failed completion preserves the original task and makes no automatic retry", async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return Response.json({ mode: "mock", error: { code: "test_error", message: "保存できませんでした" } }, { status: 500 });
  };
  await assert.rejects(completeTask(task), { status: 500 });
  assert.equal(calls, 1);
  assert.equal(task.status, "open");
});

test("wrong task IDs, wrong patients and unconfirmed changes never appear as saved", async () => {
  for (const updated of [
    { ...task, id: "t_other", status: "done" },
    { ...task, patient_id: "p303", status: "done" }, task,
  ]) {
    globalThis.fetch = async () => Response.json({ mode: "mock", task: updated });
    await assert.rejects(completeTask(task), { code: "invalid_response" });
  }
  globalThis.fetch = async () => Response.json({ mode: "mock", task });
  await assert.rejects(changeTaskUrgency(task, { urgency: "said_urgent" }), { code: "invalid_response" });
});

test("invalid metadata and duplicate IDs fail the list instead of hiding tasks", async () => {
  for (const tasks of [
    [task, task], [{ ...task, patient_id: undefined }], [{ ...task, done_at: "invalid" }],
    [{ ...task, cue: { kind: "unknown", text: "手がかり" } }],
  ]) {
    globalThis.fetch = async () => Response.json({ mode: "mock", tasks });
    await assert.rejects(loadTasks(), { code: "invalid_response" });
  }
});

test("expired tasks and intentional cancellation retain their error identity", async () => {
  globalThis.fetch = async () => Response.json({ mode: "mock", error: { code: "task_not_found", message: "期限切れです" } }, { status: 404 });
  await assert.rejects(completeTask(task), { status: 404, code: "task_not_found" });
  const controller = new AbortController();
  globalThis.fetch = async (url, options) => new Promise((resolve, reject) => {
    options.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
  });
  const pending = completeTask(task, { signal: controller.signal });
  controller.abort();
  await assert.rejects(pending, { code: "aborted" });
});

test("authentication cleanup clears task filters, errors and pending operations", () => {
  setTaskState({ tasks: [task], view: "done", patientId: "p302", errors: { t_test: "保存失敗" }, pendingIds: [task.id] });
  clearPatientData();
  const state = getState();
  assert.deepEqual(state.tasks, []);
  assert.deepEqual(state.pendingTaskIds, []);
  assert.deepEqual(state.taskErrors, {});
  assert.equal(state.taskPatientId, "");
  assert.equal(state.taskView, "open");
});

test("a chosen urgency is saved with the existing PATCH contract", async () => {
  const controller = new AbortController();
  globalThis.fetch = async (url, options) => {
    assert.equal(url.pathname, "/api/tasks/t_test");
    assert.equal(options.method, "PATCH");
    assert.equal(options.headers.get("X-Passcode"), "test-only-passcode");
    assert.deepEqual(JSON.parse(options.body), { urgency: "timed" });
    return Response.json({ mode: "mock", task: { ...task, urgency: "timed", urgency_set_by: "nurse" } });
  };
  const updated = await changeTaskUrgency(task, { urgency: "timed", signal: controller.signal });
  assert.equal(updated.urgency, "timed");
  assert.equal(updated.urgency_set_by, "nurse");
  assert.equal(task.urgency, "none");
});

test("an invalid or missing urgency choice cannot send a task update", () => {
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; throw new Error("Unexpected request"); };
  assert.throws(() => changeTaskUrgency(task, { urgency: "invalid" }), { code: "invalid_urgency" });
  assert.throws(() => changeTaskUrgency(task), { code: "invalid_urgency" });
  assert.equal(calls, 0);
});

test("failed urgency updates preserve the task urgency without automatically retrying", async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return Response.json({ mode: "mock", error: { code: "save_failed", message: "保存できませんでした" } }, { status: 500 });
  };
  await assert.rejects(changeTaskUrgency(task, { urgency: "said_urgent" }), { status: 500 });
  assert.equal(calls, 1);
  assert.equal(task.urgency, "none");
});

test("reopening sends only status open and retains the completed task until success", async () => {
  const done = { ...task, status: "done", done_at: "2026-11-08T10:00:00+09:00" };
  let finish;
  globalThis.fetch = async (url, options) => {
    assert.equal(url.pathname, "/api/tasks/t_test");
    assert.equal(options.method, "PATCH");
    assert.deepEqual(JSON.parse(options.body), { status: "open" });
    return new Promise((resolve) => { finish = resolve; });
  };
  const pending = reopenTask(done);
  assert.equal(done.status, "done");
  finish(Response.json({ mode: "mock", task }));
  const updated = await pending;
  assert.equal(updated.status, "open");
  assert.equal(updated.done_at, null);
  assert.equal(updated.urgency, done.urgency);
  assert.equal(done.status, "done");
});

test("failed reopening preserves the completed task and does not automatically retry", async () => {
  const done = { ...task, status: "done", done_at: "2026-11-08T10:00:00+09:00" };
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return Response.json({ mode: "mock", error: { code: "save_failed", message: "保存できませんでした" } }, { status: 500 });
  };
  await assert.rejects(reopenTask(done), { status: 500 });
  assert.equal(calls, 1);
  assert.equal(done.status, "done");
  assert.equal(done.done_at, "2026-11-08T10:00:00+09:00");
});
