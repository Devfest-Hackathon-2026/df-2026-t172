import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { afterEach, beforeEach, test } from "node:test";
import { createAudioReview, createTextReview, ReviewSession, transcriptError } from "../js/records.js";
import { displayName, loadPatients } from "../js/patients.js";
import { loadRecord, loadRecords } from "../js/history.js";
import { taskPatients } from "../js/tasks.js";
import { clearPatientData, getState, openTextInput, selectPatient, setReview, setTranscript } from "../js/state.js";

const fixture = JSON.parse(await readFile(new URL("../../backend/mock/draft_s1.json", import.meta.url), "utf8"));
const stopped = JSON.parse(await readFile(new URL("../../backend/mock/draft_s3.json", import.meta.url), "utf8"));
const originalFetch = globalThis.fetch;
const review = (source = fixture) => new ReviewSession(structuredClone(source));
const verified = (checks = []) => Response.json({ mode: "mock", checks, missing: fixture.missing, entail_seals: [] });

beforeEach(() => {
  globalThis.window = Object.assign(new EventTarget(), { location: { origin: "http://localhost:8765" },
    sessionStorage: { getItem: () => "test-only-passcode", removeItem() {} } });
  clearPatientData();
});
afterEach(() => { clearPatientData(); globalThis.fetch = originalFetch; delete globalThis.window; });

test("display names use full names and fall back safely without changing surnames", async () => {
  const patient = { ...fixture.patient, full_name: "田中 一郎", full_kana: "たなか いちろう" };
  globalThis.fetch = async () => Response.json({ mode: "mock", patients: [patient] });
  const [loaded] = await loadPatients();
  assert.equal(displayName(loaded), "田中 一郎");
  assert.equal(loaded.name, "田中");
  assert.equal(displayName({ ...patient, full_name: "" }), "田中");
  assert.equal(displayName({ ...patient, full_name: "  " }), "田中");
  assert.equal(displayName({ name: "旧形式" }), "旧形式");
  assert.equal(taskPatients([{ patient_id: patient.id, ...patient }])[0].full_name, patient.full_name);
});

test("record summaries and details retain full names as well as surnames", async () => {
  const base = { record_id: "r_p302_full_name", patient_id: "p302", room: "302", name: "田中", full_name: "田中 一郎", created_at: "2026-11-08T09:00:00+09:00" };
  const detail = { ...fixture.draft, ...base, chart_text: "【302号室A 田中 一郎様】\nS) 記録",
    evidence_utterances: [], kept_after_check: [], patient_check: { level: "ok", confirmed_by_nurse: false, note: null } };
  globalThis.fetch = async (url) => Response.json(url.pathname === "/api/records"
    ? { mode: "mock", records: [{ ...base, s_preview: "記録", o_preview: null, request_count: 0 }] }
    : { mode: "mock", record: detail });
  assert.equal((await loadRecords())[0].full_name, base.full_name);
  const loaded = await loadRecord(base.record_id);
  assert.equal(loaded.full_name, base.full_name);
  assert.equal(loaded.name, base.name);
  assert.equal(loaded.chart_text, detail.chart_text);
});

test("pasted text is sent unchanged as JSON, without a microphone or invented recording times", async () => {
  const transcript = "看護師: 302号室の田中さん、体温は36.8度です。\n患者: 昨夜は眠れませんでした。";
  globalThis.fetch = async (url, options) => {
    assert.equal(url.pathname, "/api/drafts");
    assert.equal(options.headers.get("Content-Type"), "application/json");
    assert.equal(options.headers.get("X-Passcode"), "test-only-passcode");
    assert.deepEqual(JSON.parse(options.body), { patient_id: "p302", transcript, first_speaker: "auto" });
    return Response.json({ ...fixture, input: "text" });
  };
  const session = await createTextReview(fixture.patient, transcript);
  assert.equal(session.input, "text");
  assert.equal(session.audio, null);
  assert.equal(session.audioUrl, null);
  assert.equal(session.timing.recording_started, null);
  assert.equal(session.timing.recording_stopped, null);
  session.dispose();
});

test("text limits count characters and utterances, rejecting empty speaker-only lines", () => {
  assert.equal(transcriptError("🙂".repeat(5000)), "");
  assert.notEqual(transcriptError("🙂".repeat(5001)), "");
  assert.equal(transcriptError(Array(200).fill("患者: はい").join("\n")), "");
  assert.notEqual(transcriptError(Array(201).fill("患者: はい").join("\n")), "");
  for (const text of ["", " \n ", "看護師:", "患者： "]) assert.notEqual(transcriptError(text), "");
  assert.equal(transcriptError("話者不明の発言"), "");
});

test("invalid text sends no request; failed generation makes no retry or fake success", async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return Response.json({ mode: "mock", error: { code: "draft_failed", message: "失敗しました" } }, { status: 502 });
  };
  await assert.rejects(createTextReview(fixture.patient, "患者:"), { code: "invalid_transcript" });
  assert.equal(calls, 0);
  await assert.rejects(createTextReview(fixture.patient, "患者: はい"), { status: 502 });
  assert.equal(calls, 1);
});

test("wrong text response input or patient cannot be attached to the selected patient", async () => {
  for (const data of [fixture, { ...fixture, input: "text", patient: { ...fixture.patient, id: "p303" } }]) {
    globalThis.fetch = async () => Response.json(data);
    await assert.rejects(createTextReview(fixture.patient, "患者: はい"), { code: "invalid_response" });
  }
});

test("paste buffer is cleared on successful review handoff and authentication/discard cleanup", () => {
  selectPatient(fixture.patient);
  openTextInput(); setTranscript("患者: 手元だけの入力");
  assert.equal(getState().consentConfirmed, false);
  setReview(review());
  assert.equal(getState().transcript, "");
  clearPatientData();
  openTextInput(); setTranscript("患者: 再入力"); clearPatientData();
  assert.equal(getState().transcript, "");
  assert.equal(getState().inputMethod, "audio");
});

test("all supported manual additions are nurse-authored and blank rows block verification and saving", async () => {
  const session = review(); let calls = 0;
  globalThis.fetch = async () => { calls += 1; return verified(); };
  for (const kind of ["soap.S", "soap.O", "requests", "doctor_questions", "manual_needed"]) {
    const path = session.addElement(kind);
    assert.ok(path);
    assert.deepEqual(session.target(path).evidence, []);
    assert.equal(session.target(path).added_by, "nurse");
  }
  assert.equal(await session.verify(), false);
  assert.equal(calls, 0);
  assert.equal(session.gate().ready, false);
  assert.throws(() => session.confirmationData());
  session.dispose();
});

test("manual entries preserve optional evidence and chosen urgency in the confirmation payload", async () => {
  const session = review();
  const path = session.addElement("requests");
  session.setElement(path, "娘への電話を手伝ってほしい");
  session.setRequestUrgency(1, "timed");
  assert.equal(session.setEvidence(path, "u15", true), true);
  globalThis.fetch = async (url, options) => {
    assert.equal(url.pathname, "/api/verify");
    const body = JSON.parse(options.body);
    assert.equal(body.entail, false);
    assert.deepEqual(body.draft.requests[1], { text: "娘への電話を手伝ってほしい", added_by: "nurse", evidence: ["u15"], urgency: "timed", cue: null });
    return verified();
  };
  await session.verify();
  assert.equal(session.gate().ready, true);
  const body = session.confirmationData();
  assert.equal(body.draft.requests[1].added_by, "nurse");
  assert.deepEqual(body.utterances, fixture.utterances);
  session.dispose();
});

test("evidence selection is limited to three existing utterances and cannot edit original AI evidence", () => {
  const session = review(), path = session.addElement("soap.S");
  session.setElement(path, "手入力した患者の訴え");
  for (const id of ["u1", "u2", "u3"]) assert.equal(session.setEvidence(path, id, true), true);
  assert.equal(session.setEvidence(path, "u4", true), false);
  assert.equal(session.setEvidence(path, "u999", true), false);
  assert.equal(session.setEvidence("soap.S[0]", "u1", true), false);
  assert.equal(session.setEvidence(path, "u2", false), true);
  assert.deepEqual(session.target(path).evidence, ["u1", "u3"]);
  session.dispose();
});

test("editing original AI text or copying it into a new row cannot relabel it as nurse-authored", () => {
  const session = review();
  session.setSoap("S", 0, "看護師が修正した既存AI文");
  assert.equal(session.draft.soap.S[0].added_by, "ai");
  const path = session.addElement("soap.S");
  session.setElement(path, ` ${fixture.draft.soap.S[0].text} `);
  assert.equal(session.target(path).added_by, "ai");
  assert.equal(session.needsEntail, true);
  session.setElement(path, "新たに入力した別の内容");
  assert.equal(session.target(path).added_by, "nurse");
  session.dispose();
});

test("removing a manual addition preserves original AI indexes, stop checks and decisions", async () => {
  const session = review(stopped);
  session.decide("soap.S[2]", "keep");
  const original = structuredClone(session.draft.soap.S);
  const path = session.addElement("soap.S"); session.setElement(path, "追加した文");
  assert.equal(session.removeAdded("soap.S[0]"), false);
  assert.equal(session.removeAdded(path), true);
  assert.deepEqual(session.draft.soap.S, original);
  globalThis.fetch = async () => Response.json({ mode: "mock", checks: [], missing: stopped.missing, entail_seals: [] });
  await session.verify();
  assert.equal(session.action("soap.S[2]"), "keep");
  assert.equal(session.checkLevel("soap.S[2]"), "stop");
  session.dispose();
});

test("removing before an appended AI copy drops shifted verdicts and requires fresh entail verification", async () => {
  const session = review();
  const first = session.addElement("soap.S"); session.setElement(first, "新しい手入力");
  const second = session.addElement("soap.S"); session.setElement(second, fixture.draft.soap.S[0].text);
  const check = { path: second, code: "no_evidence", level: "stop", message: "根拠なし" };
  globalThis.fetch = async () => verified([check]);
  await session.verify();
  session.removeAdded(first);
  assert.equal(session.draft.soap.S.length, 2);
  assert.equal(session.checks.some((c) => c.path === second), false);
  assert.equal(session.needsEntail, true);
  assert.equal(session.gate().ready, false);
  session.dispose();
});

test("manual entry limits match the existing API contract", () => {
  const data = structuredClone(fixture);
  data.draft.soap.S = Array.from({ length: 50 }, () => structuredClone(fixture.draft.soap.S[0]));
  data.draft.requests = Array.from({ length: 30 }, () => structuredClone(fixture.draft.requests[0]));
  const session = review(data);
  assert.equal(session.addElement("soap.S"), null);
  assert.equal(session.addElement("requests"), null);
  assert.equal(session.addElement("unsupported"), null);
  session.dispose();
});

test("stop colors remain stops after keep; edited or verifying data is pending and cannot be acknowledged", async () => {
  const session = review(stopped);
  assert.equal(session.checkLevel("soap.S[2]"), "stop");
  session.decide("soap.S[2]", "keep");
  assert.equal(session.checkLevel("soap.S[2]"), "stop");
  session.setSoap("S", 2, "修正した文章");
  assert.equal(session.checkLevel("soap.S[2]"), "pending");
  session.decide("soap.S[2]", "keep");
  assert.equal(session.action("soap.S[2]"), null);
  globalThis.fetch = async () => verified([{ path: "soap.S[2]", code: "entail_not_supported", level: "stop", message: "要確認" }]);
  await session.verify();
  assert.equal(session.checkLevel("soap.S[2]"), "stop");
  assert.equal(session.gate().ready, false);
  session.dispose();
});

test("manual controls cannot mutate a confirmation that is already being saved", async () => {
  const session = review(), path = session.addElement("requests"); session.setElement(path, "手入力した依頼");
  globalThis.fetch = async () => verified(); await session.verify();
  let finish;
  globalThis.fetch = async (url, options) => new Promise((resolve) => { finish = () => resolve(Response.json({ mode: "mock",
    record_id: `r_p302_${JSON.parse(options.body).confirm_id}`, chart_text: "確定した文章", tasks_created: [] })); });
  const saving = session.confirm();
  assert.equal(session.addElement("soap.O"), null);
  session.setElement(path, "保存中の書き換え"); session.setRequestUrgency(1, "timed");
  assert.equal(session.setEvidence(path, "u1", true), false);
  assert.equal(session.removeAdded(path), false);
  assert.equal(session.target(path).text, "手入力した依頼");
  assert.equal(session.target(path).urgency, "none");
  finish(); await saving;
  assert.equal(session.addedElements.size, 0);
  assert.equal(session.originalAiTexts.size, 0);
});

test("transcript usage follows manual evidence and excludes deleted elements", async () => {
  const session = review(stopped);
  session.decide("soap.S[2]", "delete");
  const path = session.addElement("requests"); session.setElement(path, "手入力の依頼"); session.setEvidence(path, "u2", true);
  assert.equal(session.usedEvidenceIds().has("u2"), true);
  session.removeAdded(path);
  assert.equal(session.usedEvidenceIds().has("u2"), false);
  session.dispose();
});

test("both draft input formats transmit each supported first speaker without altering the source", async () => {
  const transcript = "看護師: こんにちは\n患者: はい";
  const recording = { audio: new Blob(["test audio"], { type: "audio/webm" }), durationSeconds: 2,
    startedAt: new Date("2026-11-08T01:00:00Z"), stoppedAt: new Date("2026-11-08T01:00:02Z") };
  for (const firstSpeaker of ["auto", "nurse", "patient"]) {
    globalThis.fetch = async (url, options) => {
      const audio = options.body instanceof FormData;
      if (audio) {
        assert.equal(options.body.get("first_speaker"), firstSpeaker);
        assert.equal(await options.body.get("audio").text(), "test audio");
      } else assert.deepEqual(JSON.parse(options.body), { patient_id: "p302", transcript, first_speaker: firstSpeaker });
      return Response.json({ ...fixture, input: audio ? "audio" : "text" });
    };
    (await createAudioReview(fixture.patient, recording, { consentConfirmed: true, firstSpeaker })).dispose();
    (await createTextReview(fixture.patient, transcript, { firstSpeaker })).dispose();
  }
});

test("unsupported first speakers cannot reach the draft API", async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; throw new Error("Unexpected request"); };
  for (const firstSpeaker of ["unknown", "", null]) {
    await assert.rejects(createTextReview(fixture.patient, "患者: はい", { firstSpeaker }), { code: "invalid_first_speaker" });
    await assert.rejects(createAudioReview(fixture.patient, null, { consentConfirmed: true, firstSpeaker }), { code: "invalid_first_speaker" });
  }
  assert.equal(calls, 0);
});
