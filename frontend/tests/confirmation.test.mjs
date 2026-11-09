import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { afterEach, beforeEach, test } from "node:test";
import { ReviewSession, isoJst } from "../js/records.js";
import { clearPatientData, clearReview, getState, selectPatient, setConfirmedRecord, setExportState, setReview } from "../js/state.js";

const originalFetch = globalThis.fetch;
const fixture = JSON.parse(await readFile(new URL("../../backend/mock/draft_s1.json", import.meta.url), "utf8"));
const stopped = JSON.parse(await readFile(new URL("../../backend/mock/draft_s3.json", import.meta.url), "utf8"));
const signature = [{ path: "soap.S[0]", verdict: "supported", reason: "test", sig: "test-signature" }];
const session = (audio = null) => new ReviewSession({ ...structuredClone(fixture), entail_seals: signature, draft_token: "opaque-test-draft-token" }, { audio });
const success = (body, extras = {}) => Response.json({
  mode: "mock", record_id: `r_${body.patient_id}_${body.confirm_id}`,
  chart_text: "【302号室A 田中様】\nS) 確認した記録。\nA) \nP) ",
  tasks_created: [`t_${body.patient_id}_${body.confirm_id}_0`], ...extras,
});

beforeEach(() => {
  globalThis.window = Object.assign(new EventTarget(), {
    location: { origin: "http://localhost:8765" },
    sessionStorage: { getItem: () => "test-only-passcode", removeItem() {} },
  });
  clearPatientData();
});
afterEach(() => {
  clearPatientData();
  globalThis.fetch = originalFetch;
  delete globalThis.window;
});

test("confirmation uses the specified JSON contract, a safe ID and real JST timestamps", async () => {
  const review = session();
  let sent;
  globalThis.fetch = async (url, options) => {
    assert.equal(url.pathname, "/api/records");
    assert.equal(options.method, "POST");
    assert.equal(options.headers.get("X-Passcode"), "test-only-passcode");
    assert.equal(options.headers.get("Content-Type"), "application/json");
    sent = JSON.parse(options.body);
    return success(sent);
  };
  const result = await review.confirm();
  assert.deepEqual(Object.keys(sent).sort(), ["confirm_id", "patient_id", "patient_confirmed", "utterances", "draft", "entail_seals", "draft_token", "decisions", "timing", "ui_counts"].sort());
  assert.match(sent.confirm_id, /^[A-Za-z0-9_-]{1,40}$/);
  assert.deepEqual(sent.utterances, fixture.utterances);
  assert.deepEqual(sent.entail_seals, signature);
  assert.equal(sent.draft_token, "opaque-test-draft-token");
  assert.equal(sent.draft.soap.S[0].added_by, fixture.draft.soap.S[0].added_by);
  assert.deepEqual(Object.keys(sent.timing).sort(), ["recording_started", "recording_stopped", "draft_shown", "confirmed"].sort());
  assert.equal(sent.timing.recording_started, null);
  assert.equal(sent.timing.recording_stopped, null);
  assert.match(sent.timing.draft_shown, /\+09:00$/);
  assert.match(sent.timing.confirmed, /\+09:00$/);
  assert.ok(Date.parse(sent.timing.confirmed) >= Date.parse(sent.timing.draft_shown));
  assert.equal("checks" in sent, false);
  assert.equal("audio" in sent, false);
  assert.equal(result.record_id, `r_p302_${sent.confirm_id}`);
});

test("separate confirmations have separate IDs and JST preserves the instant", () => {
  const first = session();
  const second = session();
  assert.notEqual(first.confirmationData().confirm_id, second.confirmationData().confirm_id);
  assert.equal(isoJst(new Date("2026-11-08T00:00:00.000Z")), "2026-11-08T09:00:00.000+09:00");
  first.dispose();
  second.dispose();
});

test("unconfirmed patients, unresolved stops and unverified edits never reach the save API", async () => {
  globalThis.fetch = async () => assert.fail("must not save");
  const patient = structuredClone(fixture);
  patient.patient_match.level = "confirm";
  const cases = [new ReviewSession(patient), new ReviewSession(stopped), session()];
  cases[2].setSoap("A", 0, "未検証の変更");
  for (const review of cases) {
    await assert.rejects(review.confirm(), /確認が終わっていません/);
    assert.equal(review.disposed, false);
    review.dispose();
  }
});

test("double clicks make one request and saving locks editable content", async () => {
  const review = session();
  let finish;
  let calls = 0;
  globalThis.fetch = async (_, options) => {
    calls += 1;
    const body = JSON.parse(options.body);
    return new Promise((resolve) => { finish = () => resolve(success(body)); });
  };
  const first = review.confirm();
  const second = review.confirm();
  assert.equal(first, second);
  assert.equal(calls, 1);
  review.setSoap("A", 0, "保存中の変更");
  review.setVital(0, "体温", "99");
  review.confirmPatient(true);
  assert.equal(await review.verify(), false);
  assert.equal(review.draft.soap.A, "");
  assert.equal(review.draft.vitals[0].value, "36.8");
  assert.equal(review.patientConfirmed, false);
  finish();
  await first;
  assert.equal(review.disposed, true);
});

test("successful save releases audio, transcript, signatures and retry snapshots", async () => {
  const review = session(new Blob(["test audio"]));
  const audioUrl = review.audioUrl;
  assert.equal(await (await originalFetch(audioUrl)).text(), "test audio");
  globalThis.fetch = async (_, options) => success(JSON.parse(options.body), { utterances: fixture.utterances, extra: "not retained" });
  const result = await review.confirm();
  assert.deepEqual(Object.keys(result).sort(), ["mode", "record_id", "chart_text", "tasks_created"].sort());
  assert.equal(review.audio, null);
  assert.equal(review.audioUrl, null);
  assert.equal(review.draft, null);
  assert.deepEqual(review.utterances, []);
  assert.deepEqual(review.seals, []);
  assert.equal(review.draftToken, null);
  assert.equal(review.pendingConfirmation, null);
  assert.equal(review.confirmId, null);
  assert.equal(review.timing, null);
  await assert.rejects(originalFetch(audioUrl));
});

test("network failure preserves data and retry sends the identical payload and ID", async () => {
  const review = session(new Blob(["test audio"]));
  const bodies = [];
  globalThis.fetch = async (_, options) => {
    const body = JSON.parse(options.body);
    bodies.push(body);
    if (bodies.length === 1) throw new TypeError("Connection lost");
    return success(body);
  };
  await assert.rejects(review.confirm(), { code: "network_error" });
  assert.equal(bodies.length, 1);
  assert.equal(review.canRetrySave(), true);
  assert.equal(review.utterances.length, fixture.utterances.length);
  assert.ok(review.audioUrl);
  review.setSoap("A", 0, "再送前の変更は禁止");
  review.recordEvidenceTap();
  assert.equal(review.draft.soap.A, "");
  await review.confirm();
  assert.deepEqual(bodies[1], bodies[0]);
  assert.equal(review.disposed, true);
});

test("5xx is uncertain and retains source data without an automatic retry", async () => {
  const review = session();
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return Response.json({ mode: "mock", error: { code: "test_error", message: "応答に失敗しました" } }, { status: 502 });
  };
  await assert.rejects(review.confirm(), { status: 502 });
  assert.equal(calls, 1);
  assert.equal(review.saveStatus, "uncertain");
  assert.equal(review.isLocked(), true);
  assert.ok(review.pendingConfirmation);
  assert.equal(review.utterances.length, fixture.utterances.length);
  review.dispose();
});

test("409 unresolved checks needs fresh verification and a new human decision", async () => {
  const review = session();
  const bodies = [];
  globalThis.fetch = async (url, options) => {
    const body = JSON.parse(options.body);
    if (url.pathname === "/api/verify") {
      assert.equal(body.entail, true);
      return Response.json({ mode: "mock", checks: [{ path: "soap.S[0]", level: "stop", code: "entail_unclear", message: "確認が必要" }], missing: fixture.missing, entail_seals: signature });
    }
    bodies.push(body);
    return bodies.length === 1
      ? Response.json({ mode: "mock", error: { code: "undecided_checks", message: "判断が必要です" } }, { status: 409 })
      : success(body);
  };
  await assert.rejects(review.confirm(), { status: 409 });
  assert.equal(review.disposed, false);
  assert.equal(review.gate().ready, false);
  assert.equal(review.isLocked(), false);
  await assert.rejects(review.confirm(), /確認が終わっていません/);
  assert.equal(bodies.length, 1);
  await review.verify();
  assert.equal(review.gate().ready, false);
  review.decide("soap.S[0]", "keep");
  await review.confirm();
  assert.equal(bodies[1].confirm_id, bodies[0].confirm_id);
  assert.deepEqual(bodies[1].decisions, [{ path: "soap.S[0]", action: "keep" }]);
});

test("409 patient mismatch adds a confirmation requirement and keeps the draft", async () => {
  const review = session();
  let calls = 0;
  globalThis.fetch = async (_, options) => {
    calls += 1;
    const body = JSON.parse(options.body);
    if (calls === 1) return Response.json({ mode: "mock", error: { code: "patient_not_confirmed", message: "患者を確認してください" } }, { status: 409 });
    assert.equal(body.patient_confirmed, true);
    return success(body);
  };
  await assert.rejects(review.confirm(), { status: 409 });
  assert.equal(review.patientMatch.level, "confirm");
  assert.equal(review.gate().ready, false);
  assert.equal(review.utterances.length, fixture.utterances.length);
  review.confirmPatient(true);
  assert.equal(review.gate().ready, true);
  await review.confirm();
});

test("explicitly rejected input stays editable with the source draft intact", async () => {
  const review = session();
  globalThis.fetch = async () => Response.json({ mode: "mock", error: { code: "invalid_request", message: "入力をご確認ください" } }, { status: 422 });
  await assert.rejects(review.confirm(), { status: 422 });
  assert.equal(review.isLocked(), false);
  assert.equal(review.pendingConfirmation, null);
  review.setSoap("A", 0, "修正した評価");
  assert.equal(review.draft.soap.A, "修正した評価");
  assert.equal(review.gate().ready, false);
  review.dispose();
});

test("malformed responses and another patient's record cannot appear as saved", async () => {
  for (const response of [
    { mode: "mock", record_id: "r_other_patient", chart_text: "別の記録", tasks_created: [] },
    { mode: "mock", record_id: "r_test", tasks_created: [] },
  ]) {
    const review = session();
    globalThis.fetch = async () => Response.json(response);
    await assert.rejects(review.confirm(), { code: "invalid_confirmation_response" });
    assert.equal(review.saveStatus, "uncertain");
    assert.equal(review.disposed, false);
    review.dispose();
  }
});

test("export state keeps confirmed output only and clears the review session", () => {
  const review = session();
  selectPatient(fixture.patient);
  setReview(review);
  setConfirmedRecord({ mode: "mock", record_id: "r_test", chart_text: "確認した記録", tasks_created: [], utterances: fixture.utterances });
  const state = getState();
  assert.equal(state.phase, "export");
  assert.equal(state.review, null);
  assert.equal(state.selectedPatient, null);
  assert.equal(state.consentConfirmed, false);
  assert.equal(review.disposed, true);
  assert.equal("utterances" in state.confirmedRecord, false);
  clearReview();
  assert.equal(getState().confirmedRecord, null);
  assert.equal(getState().phase, "idle");
});

test("structured export accepts only the saved record and keeps the exact clipboard text", () => {
  const saved = { mode: "mock", record_id: "r_p302_test", chart_text: "【302号室A 田中様】\nS) 原文。\nA) \nP) ", tasks_created: [] };
  setConfirmedRecord(saved);
  setExportState(saved.record_id, { record: { record_id: "r_other", chart_text: saved.chart_text }, status: "ready" });
  assert.equal(getState().confirmedRecord.details, null);
  setExportState(saved.record_id, { record: { record_id: saved.record_id, chart_text: "違う文章" }, status: "ready" });
  assert.equal(getState().confirmedRecord.details, null);
  const detail = { record_id: saved.record_id, chart_text: saved.chart_text, vitals: [{ item: "体温", value: "37.1" }] };
  setExportState(saved.record_id, { record: detail, status: "ready", error: "" });
  assert.equal(getState().confirmedRecord.details, detail);
  assert.equal(getState().confirmedRecord.chart_text, saved.chart_text);
});

test("late export detail responses cannot restore cleared data or replace a newer record", () => {
  const saved = { mode: "mock", record_id: "r_p302_old", chart_text: "古い記録", tasks_created: [] };
  const detail = { record_id: saved.record_id, chart_text: saved.chart_text };
  setConfirmedRecord(saved);
  clearPatientData();
  setExportState(saved.record_id, { record: detail, status: "ready" });
  assert.equal(getState().confirmedRecord, null);
  setConfirmedRecord({ ...saved, record_id: "r_p302_new", chart_text: "新しい記録" });
  setExportState(saved.record_id, { record: detail, status: "ready" });
  assert.equal(getState().confirmedRecord.details, null);
  assert.equal(getState().confirmedRecord.chart_text, "新しい記録");
});

test("draft token and origin markers survive editing and verification without being regenerated", async () => {
  const review = session();
  const originalAddedBy = review.draft.soap.S[0].added_by;
  review.setSoap("S", 0, "看護師が修正した下書き");
  globalThis.fetch = async (url, options) => {
    const body = JSON.parse(options.body);
    if (url.pathname === "/api/verify") {
      assert.equal("draft_token" in body, false);
      return Response.json({ mode: "mock", checks: [], missing: fixture.missing, entail_seals: [] });
    }
    assert.equal(body.draft_token, "opaque-test-draft-token");
    assert.equal(body.draft.soap.S[0].added_by, originalAddedBy);
    return success(body);
  };
  await review.verify();
  await review.confirm();
  assert.equal(review.draftToken, null);
});
