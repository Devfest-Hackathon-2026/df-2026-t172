import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { ReviewSession } from "../js/records.js";
const fixture = JSON.parse(await readFile(new URL("../../backend/mock/draft_s1.json", import.meta.url), "utf8"));
const make = () => new ReviewSession(structuredClone(fixture));

test("A12: 分割はAIの出所・根拠・元計画を保ち、後半だけ末尾の計画外へ足す", () => {
  const s = make(), source = s.draft.soap.S[0];
  const plan = s.patient.care_plans[0].id;
  s.setCarePlan("soap.S[0]", plan);
  const original = source.text;
  assert.equal(typeof s.splitSoapSentence, "function");
  const path = s.splitSoapSentence("soap.S[0]", { firstText: "創部に痛みがある。", secondText: "あまり眠れなかった。" });
  const child = s.target(path);
  assert.equal(s.draft.soap.S[0], source);
  assert.equal(source.plan_id, plan);
  assert.equal(child.plan_id, null);
  assert.equal(child.added_by, source.added_by);
  assert.deepEqual(child.evidence, source.evidence);
  assert.notEqual(child.evidence, source.evidence);
  assert.equal(s.addedElements.has(child), false);
  assert.equal(s.gate().ready, false);
  assert.equal(s.verificationPayload().entail, true);
  s.setCarePlan("soap.S[0]", null);
  assert.equal(s.canUndoSplit(path), true);
  assert.equal(s.undoSplit(path), true);
  assert.equal(source.text, original);
  assert.equal(source.plan_id, null);
  assert.equal(s.draft.soap.S.includes(child), false);
  assert.equal(s.gate().ready, false);
});

test("分割の空白・上限・削除予定・ロック中は原文を変えない", () => {
  for (const firstText of ["", " \t\n　", "x".repeat(5001)]) {
    const s = make(), before = structuredClone(s.draft);
    assert.equal(typeof s.splitSoapSentence, "function");
    assert.equal(s.splitSoapSentence("soap.S[0]", { firstText, secondText: "後半" }), null);
    assert.deepEqual(s.draft, before);
  }
  for (const state of ["saving", "uncertain", "verifying", "limit", "deleted"]) {
    const s = make();
    if (state === "verifying") s.status = state;
    else if (state === "limit") while (s.draft.soap.S.length < 50) s.draft.soap.S.push(structuredClone(s.draft.soap.S[0]));
    else if (state === "deleted") { s.checks.push({ path: "soap.S[0]", level: "stop", code: "no_evidence", message: "確認" }); s.decide("soap.S[0]", "delete"); }
    else s.saveStatus = state;
    const before = structuredClone(s.draft);
    assert.equal(s.splitSoapSentence("soap.S[0]", { firstText: "前", secondText: "後" }), null);
    assert.deepEqual(s.draft, before);
  }
});

test("取消で番号が詰まる範囲の署名と確認は残さず、無関係な根拠は保つ", () => {
  const s = make();
  assert.equal(typeof s.splitSoapSentence, "function");
  const path = s.splitSoapSentence("soap.S[0]", { firstText: "前", secondText: "後" });
  const extra = s.addElement("soap.S"); s.setElement(extra, "さらに追加");
  s.seals.push({ path: extra, verdict: "supported", sig: "test-only", reason: "" });
  s.checks.push({ path: extra, level: "warn", code: "no_evidence", message: "確認" });
  assert.equal(s.undoSplit(path), true);
  assert.equal(s.seals.some((x) => x.path === extra), false);
  assert.equal(s.checks.some((x) => x.path === extra), false);
  assert.equal(s.draft.soap.S.at(-1).text, "さらに追加");
});

test("手入力の分割・連続分割・元文削除・セッション破棄を扱う", () => {
  const s = make(), source = s.addElement("soap.O"); s.setElement(source, "前と後");
  assert.equal(typeof s.splitSoapSentence, "function");
  const child = s.splitSoapSentence(source, { firstText: "前", secondText: "後" });
  assert.equal(s.addedElements.has(s.target(child)), true);
  const grandchild = s.splitSoapSentence(child, { firstText: "後の前", secondText: "後の後" });
  assert.equal(s.canUndoSplit(child), false);
  assert.equal(s.undoSplit(grandchild), true);
  assert.equal(s.undoSplit(child), true);
  const next = s.splitSoapSentence(source, { firstText: "前", secondText: "後" });
  s.removeAdded(source);
  assert.equal(s.canUndoSplit(`soap.O[0]`), false);
  s.dispose();
  assert.equal(s.canUndoSplit(next), false);
});

test("元の文を消す選択をした間は、後半からの取消でも勝手に復活させない", () => {
  const s = make();
  const child = s.splitSoapSentence("soap.S[0]", { firstText: "前", secondText: "後" });
  s.status = "verified"; s.verifiedRevision = s.revision;
  s.checks.push({ path: "soap.S[0]", level: "stop", code: "no_evidence", message: "確認" });
  s.decide("soap.S[0]", "delete");
  assert.equal(s.canUndoSplit(child), false);
  assert.equal(s.undoSplit(child), false);
  assert.equal(s.action("soap.S[0]"), "delete");
});

test("A04: 手入力分割の取消で後ろのAI文が詰まったら二段目も再確認する", () => {
  const s = make();
  const manual = s.addElement("soap.S"); s.setElement(manual, "手入力の元文");
  const manualChild = s.splitSoapSentence(manual, { firstText: "手入力前半", secondText: "手入力後半" });
  const aiChild = s.splitSoapSentence("soap.S[0]", { firstText: "AI文の前半", secondText: "AI文の後半" });
  s.status = "verified"; s.verifiedRevision = s.revision; s.needsEntail = false;
  s.seals = [{ path: aiChild, verdict: "supported", reason: "", sig: "test-only" }];
  assert.equal(s.undoSplit(manualChild), true);
  assert.equal(s.seals.length, 0);
  assert.equal(s.verificationPayload().entail, true);
});

test("A12: 手入力欄へ貼ったAI原文を分割してもAI由来を失わない", () => {
  const s = make(), aiText = s.draft.soap.S[0].text;
  const manual = s.addElement("soap.S"); s.setElement(manual, aiText);
  assert.equal(s.target(manual).added_by, "ai");
  const child = s.splitSoapSentence(manual, { firstText: "分けた前半", secondText: "分けた後半" });
  assert.equal(s.target(manual).added_by, "ai");
  assert.equal(s.target(child).added_by, "ai");
  assert.equal(s.addedElements.has(s.target(child)), false);
});

test("A12: 手入力文から足す後半がAI原文ならAIとして再確認する", () => {
  const s = make(), manual = s.addElement("soap.S"); s.setElement(manual, "手入力文");
  const child = s.splitSoapSentence(manual, { firstText: "手入力前半", secondText: s.draft.soap.S[0].text });
  assert.equal(s.target(child).added_by, "ai");
  assert.equal(s.addedElements.has(s.target(child)), false);
});

test("分割入力を適用する前は元文のまま確定できず、取消・文の削除で解除できる", () => {
  const s = make(), item = s.draft.soap.S[0];
  assert.equal(s.gate().ready, true);
  s.splitEdits.set(item, { firstText: "編集中", secondText: "後半" });
  assert.equal(s.gate().ready, false);
  assert.throws(() => s.confirmationData(), /確認が終わっていません/);
  s.splitEdits.delete(item); assert.equal(s.gate().ready, true);
  const path = s.addElement("soap.S"), added = s.target(path);
  s.setElement(path, "追加した文"); s.splitEdits.set(added, { firstText: "編集中", secondText: "後半" });
  s.removeAdded(path); assert.equal(s.splitEdits.size, 0);
});

test("元文または後半に未適用フォームがある間は分割を戻せない", () => {
  const s = make();
  const child = s.splitSoapSentence("soap.S[0]", { firstText: "前半", secondText: "後半" });
  for (const item of [s.draft.soap.S[0], s.target(child)]) {
    s.splitEdits.set(item, { firstText: "編集中", secondText: "別の後半" });
    assert.equal(s.canUndoSplit(child), false);
    assert.equal(s.undoSplit(child), false);
    s.splitEdits.delete(item);
  }
  assert.equal(s.canUndoSplit(child), true);
});
