import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { afterEach, beforeEach, test } from "node:test";
import { ReviewSession } from "../js/records.js";

const originalFetch = globalThis.fetch;
const fixtures = {};
for (const id of [1, 2, 3, 4, 5]) {
  fixtures[id] = JSON.parse(await readFile(new URL(`../../backend/mock/draft_s${id}.json`, import.meta.url), "utf8"));
}
const fixture = (id = 1) => structuredClone(fixtures[id]);
const signature = [{ path: "soap.S[0]", verdict: "supported", reason: "test", sig: "test-signature" }];

beforeEach(() => {
  globalThis.window = Object.assign(new EventTarget(), {
    location: { origin: "http://localhost:8765" },
    sessionStorage: { getItem: () => "test-only-passcode", removeItem() {} },
  });
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  delete globalThis.window;
});

test("AI assessment and plan are discarded; another patient's draft cannot be selected", () => {
  const data = fixture();
  data.draft.soap.A = "AI assessment";
  data.draft.soap.P = "AI plan";
  const session = new ReviewSession(data);
  assert.equal(session.draft.soap.A, "");
  assert.equal(session.draft.soap.P, "");
  assert.throws(() => new ReviewSession(data, { expectedPatientId: "another_patient" }), { code: "invalid_response" });
});

test("yellow and red matches require explicit nurse confirmation", () => {
  for (const level of ["confirm", "stop"]) {
    const data = fixture();
    data.patient_match.level = level;
    const session = new ReviewSession(data);
    assert.equal(session.gate().ready, false);
    session.patientConfirmed = true;
    assert.equal(session.gate().ready, true);
    assert.equal(session.confirmationData().patient_confirmed, true);
  }
});

test("each stopped element needs a decision; delete retains original indexes and evidence", () => {
  const session = new ReviewSession(fixture(3));
  assert.equal(session.gate().ready, false);
  session.decide("soap.S[2]", "delete");
  assert.equal(session.gate().ready, true);
  assert.equal(session.draft.soap.S.length, 3);
  const data = session.confirmationData();
  assert.deepEqual(data.decisions, [{ path: "soap.S[2]", action: "delete" }]);
  assert.deepEqual(data.draft.soap.S[2].evidence, ["u6", "u8"]);
  session.decide("soap.S[2]", "delete");
  assert.equal(session.gate().ready, false);
});

test("editing a stopped sentence revokes its decision and requires entail verification", () => {
  const session = new ReviewSession(fixture(3));
  session.decide("soap.S[2]", "keep");
  assert.equal(session.gate().ready, true);
  session.setSoap("S", 2, "だるさがあり、飲水は少しできている。");
  assert.equal(session.action("soap.S[2]"), null);
  assert.equal(session.gate().ready, false);
  const body = session.verificationPayload();
  assert.equal(body.entail, true);
  assert.deepEqual(body.draft.soap.S[2].evidence, ["u6", "u8"]);
  assert.deepEqual(body.utterances, fixtures[3].utterances);
});

test("swapping speakers preserves utterance order and draft content while revoking earlier confirmations", () => {
  const data = fixture(3);
  data.utterances.push({ id: "u99", speaker: "unknown", text: "話者不明の発言", start: 25, end: 26 });
  data.entail_seals = signature;
  data.checks.push({ path: "vitals[0]", level: "warn", code: "multiple_values", message: "値が複数" });
  const session = new ReviewSession(data);
  session.decide("soap.S[2]", "keep");
  session.confirmMultiple("vitals[0]");
  assert.equal(session.gate().ready, true);
  const draft = structuredClone(session.draft);
  const token = session.draftToken;
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; throw new Error("unexpected request"); };

  assert.equal(session.swapSpeakers(), true);
  assert.deepEqual(session.utterances, data.utterances.map((u) => ({ ...u,
    speaker: { nurse: "patient", patient: "nurse", unknown: "unknown" }[u.speaker] })));
  assert.deepEqual(session.draft, draft);
  assert.equal(session.draftToken, token);
  assert.equal(session.status, "dirty");
  assert.equal(session.needsEntail, true);
  assert.equal(session.gate().ready, false);
  assert.deepEqual(session.seals, []);
  assert.equal(session.decisions.size, 0);
  assert.equal(session.multipleConfirmed.size, 0);
  assert.equal(session.verifiedVitalData.size, 0);
  assert.throws(() => session.confirmationData());
  assert.equal(calls, 0);

  assert.equal(session.swapSpeakers(), true);
  assert.deepEqual(session.utterances, data.utterances);
  assert.equal(session.gate().ready, false);
  assert.equal(session.needsEntail, true);
  assert.equal(session.revision, 2);
  assert.deepEqual(data.utterances, [...fixtures[3].utterances, { id: "u99", speaker: "unknown", text: "話者不明の発言", start: 25, end: 26 }]);
});

test("speaker changes send a fresh entail verification and cannot be confirmed after a failed verification", async () => {
  const data = fixture();
  const session = new ReviewSession({ ...data, entail_seals: signature });
  session.swapSpeakers();
  const swapped = structuredClone(session.utterances);
  globalThis.fetch = async (_, options) => {
    const body = JSON.parse(options.body);
    assert.equal(body.entail, true);
    assert.deepEqual(body.utterances, swapped);
    assert.deepEqual(body.draft, session.draft);
    return Response.json({ mode: "mock", error: { code: "test_error", message: "再検証できませんでした" } }, { status: 502 });
  };
  await assert.rejects(session.verify(), { status: 502 });
  assert.equal(session.gate().ready, false);
  assert.equal(session.needsEntail, true);
  assert.deepEqual(session.seals, []);

  const newSeals = [{ ...signature[0], sig: "speaker-change-signature" }];
  let finish;
  globalThis.fetch = async (_, options) => {
    assert.equal(JSON.parse(options.body).entail, true);
    return new Promise((resolve) => { finish = resolve; });
  };
  const pending = session.verify();
  assert.equal(session.canSwapSpeakers(), false);
  assert.equal(session.swapSpeakers(), false);
  assert.deepEqual(session.utterances, swapped);
  finish(Response.json({ mode: "mock", checks: [{ path: "soap.S[0]", level: "stop", code: "speaker_mismatch", message: "話者を確認" }],
    missing: data.missing, entail_seals: newSeals }));
  await pending;
  assert.equal(session.gate().ready, false);
  session.decide("soap.S[0]", "keep");
  assert.deepEqual(session.confirmationData().utterances, swapped);
  assert.deepEqual(session.confirmationData().entail_seals, newSeals);
});

test("unknown-only, saving, uncertain and disposed sessions cannot swap speakers", () => {
  const unknown = fixture();
  unknown.utterances = unknown.utterances.map((u) => ({ ...u, speaker: "unknown" }));
  const unknownSession = new ReviewSession(unknown);
  assert.equal(unknownSession.swapSpeakers(), false);
  assert.equal(unknownSession.revision, 0);
  for (const saveStatus of ["saving", "uncertain"]) {
    const session = new ReviewSession(fixture());
    session.saveStatus = saveStatus;
    assert.equal(session.swapSpeakers(), false);
    assert.deepEqual(session.utterances, fixtures[1].utterances);
    assert.equal(session.revision, 0);
  }
  const disposed = new ReviewSession(fixture());
  disposed.dispose();
  assert.equal(disposed.swapSpeakers(), false);
});

test("code-only verification preserves earlier entail stop checks and opaque signatures", async () => {
  const data = fixture(3);
  data.entail_seals = signature;
  const session = new ReviewSession(data);
  session.decide("soap.S[2]", "keep");
  session.setSoap("A", 0, "看護師が手入力した内容");
  globalThis.fetch = async (_, options) => {
    const body = JSON.parse(options.body);
    assert.equal(body.entail, false);
    assert.equal(body.draft.soap.A, "看護師が手入力した内容");
    return Response.json({ mode: "mock", checks: [], missing: data.missing, entail_seals: [] });
  };
  await session.verify();
  assert.deepEqual(session.checks, fixtures[3].checks);
  assert.deepEqual(session.seals, signature);
  assert.equal(session.action("soap.S[2]"), "keep");
  assert.equal(session.gate().ready, true);
});

test("edited SOAP is sent for entail verification and new signatures replace the old ones", async () => {
  const data = fixture();
  data.entail_seals = signature;
  const session = new ReviewSession(data);
  session.setSoap("S", 0, "夜間に創部痛があったとの訴え。");
  const updated = [{ ...signature[0], sig: "updated-test-signature" }];
  globalThis.fetch = async (_, options) => {
    const body = JSON.parse(options.body);
    assert.equal(body.entail, true);
    assert.equal(body.draft.soap.S[0].text, "夜間に創部痛があったとの訴え。");
    assert.deepEqual(body.utterances, data.utterances);
    return Response.json({ mode: "mock", checks: [], missing: data.missing, entail_seals: updated });
  };
  await session.verify();
  assert.deepEqual(session.confirmationData().entail_seals, updated);
  assert.equal(session.draft.soap.S[0].text, "夜間に創部痛があったとの訴え。");
});

test("a stale verification response cannot validate a newer edit", async () => {
  const session = new ReviewSession(fixture());
  session.setSoap("S", 0, "最初の修正");
  let complete;
  globalThis.fetch = async () => new Promise((resolve) => { complete = resolve; });
  const pending = session.verify();
  session.setSoap("S", 0, "検証中にさらに修正");
  complete(Response.json({ mode: "mock", checks: [], missing: [], entail_seals: signature }));
  assert.equal(await pending, false);
  assert.equal(session.draft.soap.S[0].text, "検証中にさらに修正");
  assert.equal(session.status, "dirty");
  assert.equal(session.gate().ready, false);
  assert.notEqual(session.verifiedRevision, session.revision);
});

test("verification failure preserves edits and blocks completion", async () => {
  const session = new ReviewSession(fixture());
  session.setSoap("P", 0, "看護師が入力した計画");
  globalThis.fetch = async () => Response.json({
    mode: "mock", error: { code: "test_error", message: "再検証できませんでした" },
  }, { status: 502 });
  await assert.rejects(session.verify(), { status: 502 });
  assert.equal(session.status, "error");
  assert.equal(session.gate().ready, false);
  assert.equal(session.draft.soap.P, "看護師が入力した計画");
});

test("multiple vital values need an explicit choice, which an edit invalidates", () => {
  const session = new ReviewSession(fixture(5));
  assert.equal(session.gate().ready, false);
  session.confirmMultiple("vitals[0]");
  assert.equal(session.gate().ready, true);
  session.setVital(0, "体温", "36.7");
  assert.equal(session.gate().ready, false);
  assert.equal(session.multipleConfirmed.has("vitals[0]"), false);
});

test("manual vitals carry manual source without stale evidence; missing excludes optional blood glucose", async () => {
  const session = new ReviewSession(fixture());
  assert.deepEqual(session.getMissing(), ["呼吸数", "SpO2"]);
  session.setVital(null, "呼吸数", "16");
  session.setVital(null, "SpO2", "98");
  session.setVital(0, "体温", "36.9");
  assert.equal(session.draft.vitals[0].source, "manual");
  assert.deepEqual(session.draft.vitals[0].evidence, []);
  assert.deepEqual(session.getMissing(), []);
  assert.equal(session.gate().ready, false);
  globalThis.fetch = async (_, options) => {
    assert.equal(JSON.parse(options.body).entail, false);
    return Response.json({ mode: "mock", checks: [], missing: [], entail_seals: [] });
  };
  await session.verify();
  assert.equal(session.gate().ready, true);
});

test("a changed verification warning cannot reuse an earlier decision", async () => {
  const data = fixture(3);
  const session = new ReviewSession(data);
  session.decide("soap.S[2]", "keep");
  globalThis.fetch = async () => Response.json({ mode: "mock", checks: [{
    path: "soap.S[2]", level: "stop", code: "speaker_mismatch", message: "別の確認が必要",
  }], missing: data.missing, entail_seals: [] });
  await session.verify();
  assert.equal(session.action("soap.S[2]"), null);
  assert.equal(session.gate().ready, false);
});

test("discard releases audio, transcript and signatures and prevents later completion", () => {
  const data = fixture();
  data.entail_seals = signature;
  const session = new ReviewSession(data, { audio: new Blob(["test audio"]) });
  assert.ok(session.audioUrl);
  session.dispose();
  assert.equal(session.audioUrl, null);
  assert.equal(session.audio, null);
  assert.deepEqual(session.utterances, []);
  assert.deepEqual(session.seals, []);
  assert.equal(session.draft, null);
  assert.equal(session.gate().ready, false);
  assert.throws(() => session.confirmationData());
});
