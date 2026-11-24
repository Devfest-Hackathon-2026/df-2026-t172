import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { afterEach, beforeEach, test } from "node:test";
import { ReviewSession } from "../js/records.js";

const fixture = JSON.parse(await readFile(new URL("../../backend/mock/draft_s3.json", import.meta.url), "utf8"));
const originalFetch = globalThis.fetch;
const make = () => new ReviewSession(structuredClone(fixture));
beforeEach(() => {
  globalThis.window = { location: { origin: "http://localhost:8765" }, sessionStorage: { getItem: () => "local-test-only" } };
});
afterEach(() => { globalThis.fetch = originalFetch; delete globalThis.window; });

test("A14: 計画だけの変更は根拠・文オブジェクト・残す消す・署名を保ち通信しない", () => {
  const s = make();
  s.decide("soap.S[2]", "keep");
  const item = s.draft.soap.S[2];
  const seals = structuredClone(s.seals);
  const revision = s.revision;
  const plan = s.patient.care_plans[0].id;
  globalThis.fetch = () => assert.fail("計画変更で通信しない");
  assert.equal(typeof s.setCarePlan, "function");
  assert.equal(s.setCarePlan("soap.S[2]", plan), true);
  assert.equal(s.draft.soap.S[2], item);
  assert.equal(s.action("soap.S[2]"), "keep");
  assert.equal(s.revision, revision);
  assert.deepEqual(s.seals, seals);
  assert.equal(s.gate().ready, true);
  s.setSoap("S", 2, "別の文");
  assert.equal(s.action("soap.S[2]"), null);
  assert.equal(s.gate().ready, false);
});

test("R03: 不明計画・SOAP以外・処理中の変更は無変更", () => {
  const s = make();
  assert.equal(typeof s.setCarePlan, "function");
  const before = structuredClone(s.draft);
  assert.equal(s.setCarePlan("soap.S[0]", "unknown"), false);
  assert.equal(s.setCarePlan("requests[0]", null), false);
  for (const status of ["verifying", "saving", "uncertain"]) {
    s.status = status === "verifying" ? "verifying" : "verified";
    s.saveStatus = status === "verifying" ? "idle" : status;
    assert.equal(s.setCarePlan("soap.S[0]", s.patient.care_plans[0].id), false);
  }
  assert.deepEqual(s.draft, before);
});

test("A14: 下書きは受信値によらず計画外。旧形式は空計画、不正計画は拒否", () => {
  const d = structuredClone(fixture);
  d.draft.soap.S[0].plan_id = "server-choice";
  assert.equal(new ReviewSession(d).draft.soap.S[0].plan_id, null);
  delete d.patient.care_plans;
  assert.deepEqual(new ReviewSession(d).patient.care_plans, []);
  d.patient.care_plans = null;
  assert.throws(() => new ReviewSession(d), { code: "invalid_response" });
});

test("R03: 削除予定文の計画は送信コピーだけnullになり、不確実な再送は同じ内容", async () => {
  const s = make();
  assert.equal(typeof s.setCarePlan, "function");
  const plan = s.patient.care_plans[0].id;
  s.setCarePlan("soap.S[2]", plan);
  s.decide("soap.S[2]", "delete");
  const sent = [];
  globalThis.fetch = async (_, options) => { sent.push(JSON.parse(options.body)); throw new Error("network"); };
  await assert.rejects(s.confirm());
  assert.equal(sent[0].draft.soap.S[2].plan_id, null);
  assert.equal(s.draft.soap.S[2].plan_id, plan);
  await assert.rejects(s.confirm());
  assert.deepEqual(sent[1], sent[0]);
});

test("表示グループは元の配列・警告パス・文オブジェクトを変えない", async () => {
  const { groupSoapByPlan, normalizeCarePlans } = await import("../js/care-plans.js");
  const s = make();
  const plan = s.patient.care_plans[0];
  s.draft.soap.S[1].plan_id = plan.id;
  const groups = groupSoapByPlan(s.draft.soap, s.patient.care_plans);
  assert.equal(groups.find((g) => g.id === plan.id).entries[0].path, "soap.S[1]");
  assert.equal(groups.at(-1).id, null);
  assert.equal(s.draft.soap.S[1], groups[0].entries[0].item);
  assert.throws(() => normalizeCarePlans([plan, plan]), { code: "invalid_response" });
  assert.deepEqual(normalizeCarePlans(undefined), []);
});
