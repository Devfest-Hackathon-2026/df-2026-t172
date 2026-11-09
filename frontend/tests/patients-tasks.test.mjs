import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import { loadPatients, sortPatients } from "../js/patients.js";
import { changeTaskUrgency, groupOpenTasks, loadOpenTasks } from "../js/tasks.js";
import { clearPatientData, confirmConsent, getState, selectPatient } from "../js/state.js";

const originalFetch = globalThis.fetch;
const patient = { id: "p302", room: "302", bed: "A", name: "架空患者" };
const task = {
  id: "test_task", room: "302", name: "架空患者", patient_id: "p302",
  text: "タオルをもう1枚", patient_words: ["タオル、もう1枚もらえるかな"],
  urgency: "none", status: "open", created_at: "2026-11-08T09:00:00+09:00",
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

test("patients are sorted numerically by room and then bed without changing the response", () => {
  const patients = [
    { ...patient, id: "p10", room: "10", bed: "B" },
    { ...patient, id: "p2b", room: "2", bed: "B" },
    { ...patient, id: "p2a", room: "2", bed: "A" },
  ];
  assert.deepEqual(sortPatients(patients).map((p) => p.id), ["p2a", "p2b", "p10"]);
  assert.deepEqual(patients.map((p) => p.id), ["p10", "p2b", "p2a"]);
});

test("malformed patient rows cannot enter the selection list", async () => {
  globalThis.fetch = async () => Response.json({ mode: "mock", patients: [{ id: "p302", name: "架空患者" }] });
  await assert.rejects(loadPatients(), { code: "invalid_response" });
});

test("consent requires selection and is reset when the patient changes or selection is canceled", () => {
  assert.equal(confirmConsent(), false);
  selectPatient(patient);
  assert.equal(getState().consentConfirmed, false);
  assert.equal(confirmConsent(), true);
  assert.equal(getState().consentConfirmed, true);
  selectPatient({ ...patient, id: "p303" });
  assert.equal(getState().consentConfirmed, false);
  selectPatient(null);
  assert.equal(getState().selectedPatient, null);
  assert.equal(confirmConsent(), false);
});

test("task groups preserve urgency order, time order and patient wording, excluding completed tasks", () => {
  const tasks = [
    { ...task, id: "none_late", created_at: "2026-11-08T01:00:00Z" },
    { ...task, id: "timed", urgency: "timed" },
    { ...task, id: "none_early" },
    { ...task, id: "urgent", urgency: "said_urgent" },
    { ...task, id: "done", status: "done" },
  ];
  const groups = groupOpenTasks(tasks);
  assert.deepEqual(groups.map((group) => group.value), ["said_urgent", "timed", "none"]);
  assert.deepEqual(groups.flatMap((group) => group.tasks.map((t) => t.id)), ["urgent", "timed", "none_early", "none_late"]);
  assert.deepEqual(groups[2].tasks[0].patient_words, task.patient_words);
  assert.equal(tasks[0].id, "none_late");
});

test("task retrieval requests only open tasks with authentication", async () => {
  globalThis.fetch = async (url, options) => {
    assert.equal(url.pathname, "/api/tasks");
    assert.equal(url.searchParams.get("status"), "open");
    assert.equal(options.headers.get("X-Passcode"), "test-only-passcode");
    return Response.json({ mode: "mock", tasks: [task, { ...task, id: "done", status: "done" }] });
  };
  assert.equal((await loadOpenTasks()).length, 1);
});

test("invalid task dates or categories produce an error instead of hiding tasks", async () => {
  for (const invalid of [{ ...task, urgency: "critical" }, { ...task, created_at: "not-a-date" }]) {
    globalThis.fetch = async () => Response.json({ mode: "mock", tasks: [invalid] });
    await assert.rejects(loadOpenTasks(), { code: "invalid_response" });
  }
});

test("urgency changes wait for the API result and preserve the original task", async () => {
  let complete;
  globalThis.fetch = async (url, options) => {
    assert.equal(url.pathname, "/api/tasks/test_task");
    assert.equal(options.method, "PATCH");
    assert.deepEqual(JSON.parse(options.body), { urgency: "said_urgent" });
    return new Promise((resolve) => { complete = resolve; });
  };
  const pending = changeTaskUrgency(task, { urgency: "said_urgent" });
  assert.equal(task.urgency, "none");
  complete(Response.json({ mode: "mock", task: { ...task, urgency: "said_urgent", urgency_set_by: "nurse" } }));
  const updated = await pending;
  assert.equal(updated.urgency, "said_urgent");
  assert.equal(updated.urgency_set_by, "nurse");
  assert.equal(task.urgency, "none");
});

test("failed task updates leave the original category unchanged", async () => {
  globalThis.fetch = async () => Response.json({
    mode: "mock", error: { code: "test_failure", message: "保存できませんでした" },
  }, { status: 502 });
  await assert.rejects(changeTaskUrgency(task, { urgency: "said_urgent" }), { status: 502, message: "保存できませんでした" });
  assert.equal(task.urgency, "none");
});
