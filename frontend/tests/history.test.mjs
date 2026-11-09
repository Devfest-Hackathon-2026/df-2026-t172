import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { afterEach, beforeEach, test } from "node:test";
import { loadRecord, loadRecords, recordTime, savedTarget } from "../js/history.js";
import { clearPatientData, getState, setHistoryState } from "../js/state.js";

const originalFetch = globalThis.fetch;
const fixture = JSON.parse(await readFile(new URL("../../backend/mock/draft_s1.json", import.meta.url), "utf8"));
const summary = {
  record_id: "r_p302_test", patient_id: "p302", room: "302", name: "架空患者",
  created_at: "2026-11-08T09:00:00+09:00", s_preview: "患者の訴え", o_preview: null, request_count: 1,
};
const detail = () => ({
  ...structuredClone(fixture.draft), record_id: summary.record_id, patient_id: "p302", room: "302", name: "架空患者",
  created_at: summary.created_at, chart_text: "【302号室A 架空患者様】\nS) 患者の訴え。\nA) \nP) ",
  evidence_utterances: fixture.utterances.slice(0, 2).map(({ id, speaker, text }) => ({ id, speaker, text })),
  kept_after_check: [{ path: "soap.S[0]", codes: ["entail_not_supported"], note: "看護師が確認して残した" }],
  patient_check: { level: "stop", confirmed_by_nurse: true, note: "照合で食い違いあり→看護師が確認" },
});

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

test("record list is an authenticated read, sorted newest first and limited to summary fields", async () => {
  const rows = [summary, { ...summary, record_id: "r_p302_new", created_at: "2026-11-08T01:00:00Z", utterances: ["not retained"] }];
  globalThis.fetch = async (url, options) => {
    assert.equal(url.pathname, "/api/records");
    assert.equal(url.search, "");
    assert.equal(options.method, "GET");
    assert.equal(options.headers.get("X-Passcode"), "test-only-passcode");
    assert.equal(options.body, undefined);
    return Response.json({ mode: "mock", records: rows });
  };
  const records = await loadRecords();
  assert.deepEqual(records.map((r) => r.record_id), ["r_p302_new", "r_p302_test"]);
  assert.equal("utterances" in records[0], false);
  assert.equal(rows[0].record_id, summary.record_id);
});

test("patient filter is sent to the API and mismatched patients cannot enter the result", async () => {
  globalThis.fetch = async (url) => {
    assert.equal(url.searchParams.get("patient_id"), "p302");
    return Response.json({ mode: "mock", records: [summary] });
  };
  assert.equal((await loadRecords({ patientId: "p302" })).length, 1);
  globalThis.fetch = async () => Response.json({ mode: "mock", records: [{ ...summary, patient_id: "p303" }] });
  await assert.rejects(loadRecords({ patientId: "p302" }), { code: "invalid_response" });
});

test("empty lists are valid but malformed rows and duplicates cannot be mistaken for no records", async () => {
  globalThis.fetch = async () => Response.json({ mode: "mock", records: [] });
  assert.deepEqual(await loadRecords(), []);
  for (const rows of [[{ ...summary, created_at: "bad date" }], [{ ...summary, request_count: -1 }], [summary, summary]]) {
    globalThis.fetch = async () => Response.json({ mode: "mock", records: rows });
    await assert.rejects(loadRecords(), { code: "invalid_response" });
  }
});

test("record detail preserves server chart text and confirmation notes, retaining evidence only", async () => {
  const source = { ...detail(), audio: "not retained", utterances: fixture.utterances,
    evidence_utterances: [{ ...detail().evidence_utterances[0], start: 0, end: 2, audio: "not retained" }] };
  globalThis.fetch = async (url, options) => {
    assert.equal(url.pathname, `/api/records/${summary.record_id}`);
    assert.equal(options.method, "GET");
    assert.equal(options.headers.get("X-Passcode"), "test-only-passcode");
    return Response.json({ mode: "mock", record: source });
  };
  const record = await loadRecord(summary.record_id);
  assert.equal(record.chart_text, source.chart_text);
  assert.deepEqual(record.patient_check, source.patient_check);
  assert.deepEqual(record.kept_after_check, source.kept_after_check);
  assert.equal("audio" in record, false);
  assert.equal("utterances" in record, false);
  assert.deepEqual(Object.keys(record.evidence_utterances[0]), ["id", "speaker", "text"]);
});

test("another record and malformed saved evidence cannot be presented as the requested detail", async () => {
  for (const record of [
    { ...detail(), record_id: "r_p303_other" },
    { ...detail(), patient_id: "p303" },
    { ...detail(), evidence_utterances: [{ id: "u1", text: "発言", speaker: "doctor" }] },
    { ...detail(), soap: { ...detail().soap, S: [{ text: "本文", evidence: "u1" }] } },
    { ...detail(), patient_check: { level: "red", confirmed_by_nurse: true, note: null } },
  ]) {
    globalThis.fetch = async () => Response.json({ mode: "mock", record });
    await assert.rejects(loadRecord(summary.record_id), { code: "invalid_response" });
  }
});

test("invalid record IDs never result in a request", async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; throw new Error("Must not fetch"); };
  for (const value of ["", "../patients", "r_test?secret=1", "r_test/other", `r_${"a".repeat(91)}`, null]) {
    await assert.rejects(loadRecord(value), { code: "invalid_record_id" });
  }
  assert.equal(calls, 0);
});

test("missing or expired records and connection errors stay errors without automatic retries", async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return Response.json({ mode: "mock", error: { code: "record_not_found", message: "記録がありません" } }, { status: 404 });
  };
  await assert.rejects(loadRecord(summary.record_id), { status: 404, code: "record_not_found" });
  assert.equal(calls, 1);
  globalThis.fetch = async () => { throw new TypeError("offline"); };
  await assert.rejects(loadRecords(), { code: "network_error" });
});

test("confirmation marks refer to saved array indexes without interpreting arbitrary paths", () => {
  const record = detail();
  assert.equal(savedTarget(record, "soap.S[0]"), record.soap.S[0].text);
  assert.equal(savedTarget(record, "vitals[0]"), "体温 36.8");
  assert.equal(savedTarget(record, "requests[0]"), record.requests[0].text);
  assert.equal(savedTarget(record, "soap.S[999]"), "");
  assert.equal(savedTarget(record, "__proto__.test"), "");
});

test("record time consistently uses Japan time regardless of the browser's timezone", () => {
  assert.equal(recordTime("2026-11-08T00:05:00Z"), "09:05");
  assert.equal(recordTime("2026-11-08T15:00:00Z"), "00:00");
});

test("authentication cleanup releases record lists, details and patient filters", () => {
  setHistoryState({ records: [summary], patients: [fixture.patient], record: detail(), recordId: summary.record_id,
    patientId: "p302", status: "ready", detailStatus: "ready" });
  clearPatientData();
  const history = getState().history;
  assert.deepEqual(history.records, []);
  assert.deepEqual(history.patients, []);
  assert.equal(history.record, null);
  assert.equal(history.recordId, null);
  assert.equal(history.patientId, "");
});
