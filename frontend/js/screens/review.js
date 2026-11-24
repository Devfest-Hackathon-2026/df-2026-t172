import { renderSoap } from "../components/review-soap.js?v=20261121-context-help";
import { renderPatientCard } from "../components/patient-card.js?v=20261121-context-help";
import { renderVitalCard } from "../components/vital-card.js?v=20261121-context-help";
import { renderAlertCard } from "../components/alert-card.js";
import { renderUtterance } from "../components/evidence-card.js";
import { element, panel, reviewButton } from "../components/review-dom.js";
import { addEntryButton, refreshCheckTarget, renderReviewEntry } from "../components/review-entry.js?v=20261121-context-help";

function renderChecks(session) {
  const section = panel("検証結果");
  const byPath = new Map();
  for (const check of session.checks) {
    if (!byPath.has(check.path)) byPath.set(check.path, []);
    byPath.get(check.path).push(check);
  }
  if (!byPath.size) {
    const empty = element("p", "empty-inline", "指摘なし");
    empty.dataset.checkEmpty = "";
    section.append(empty);
  }
  for (const [path, checks] of byPath) section.append(renderAlertCard(path, checks, session));
  return section;
}

function renderRequests(session) {
  const section = panel("患者からの依頼");
  for (const [index, request] of session.draft.requests.entries()) {
    section.append(renderReviewEntry(request, `requests[${index}]`, session, { index, label: `依頼 ${index + 1}件目`,
      evidenceKey: `request-evidence-${index}`, className: "review-request" }));
  }
  section.append(addEntryButton("requests", "＋ 依頼を追加", session));
  return section;
}

function renderInformation(title, key, session) {
  const section = panel(title);
  for (const [index, item] of session.draft[key].entries()) {
    section.append(renderReviewEntry(item, `${key}[${index}]`, session,
      { index, label: `${title} ${index + 1}件目`, evidenceKey: `${key}-${index}` }));
  }
  section.append(addEntryButton(key, "＋ 項目を追加", session));
  return section;
}

export function renderReview(session) {
  const view = element("div", "review-screen");
  const header = element("div", "review-heading");
  header.append(element("h1", "page-title", "記録確認"), reviewButton("破棄", "discard", "text-button danger-text"));
  view.append(header);
  view.append(element("p", "ai-note", "この画面の S・O・依頼は AI が作った下書きです。赤い枠の文は、根拠の発言から言えるか確かめて、残す／消すを選んでください。"));
  if (session.audioUrl) {
    const audio = element("audio", "recording-playback");
    audio.controls = true;
    audio.preload = "none";
    audio.src = session.audioUrl;
    audio.setAttribute("aria-label", "録音全体");
    audio.addEventListener("play", () => {
      for (const other of document.querySelectorAll("audio")) if (other !== audio) other.pause();
    });
    view.append(audio);
  }
  view.append(renderPatientCard(session), renderVitalCard(session), renderSoap(session), renderChecks(session));
  for (const section of [renderRequests(session), renderInformation("手で入力が必要（薬など）", "manual_needed", session),
    renderInformation("医師への確認", "doctor_questions", session)]) if (section) view.append(section);

  const transcript = element("details", "transcript-panel");
  transcript.dataset.detailsKey = "transcript";
  transcript.append(element("summary", "panel-heading", `会話の文字起こし（${session.utterances.length}）`));
  const speakerTools = element("div", "speaker-tools");
  const speakerStatus = element("p", "empty-inline");
  speakerStatus.dataset.speakerStatus = "";
  speakerStatus.setAttribute("role", "status");
  speakerTools.append(reviewButton("看護師と患者を入れ替える", "swap-speakers"),
    speakerStatus);
  transcript.append(speakerTools);
  const used = session.usedEvidenceIds();
  for (const utterance of session.utterances) {
    const row = renderUtterance(utterance, session);
    row.dataset.used = String(used.has(utterance.id));
    transcript.append(row);
  }
  view.append(transcript);

  const actions = element("div", "review-actions");
  const error = element("p", "form-error");
  error.dataset.verificationError = "";
  error.setAttribute("role", "alert");
  const status = element("p", "review-status");
  status.dataset.reviewStatus = "";
  status.setAttribute("role", "status");
  const buttons = element("div", "review-action-buttons");
  buttons.append(reviewButton("再検証", "verify"), reviewButton("確定", "confirm", "primary-button"));
  actions.append(error, status, buttons);
  view.append(actions);
  refreshReviewStatus(view, session);
  return view;
}

export function refreshReviewStatus(root, session) {
  const gate = session.gate();
  const missing = session.getMissing();
  const status = root.querySelector("[data-review-status]");
  const message = gate.ready
    ? missing.length ? `未入力・要確認 ${missing.length}項目（未保存）` : "確認済み（未保存）"
    : gate.reasons.join("／");
  if (status.textContent !== message) status.textContent = message;
  status.dataset.ready = String(gate.ready && !missing.length);
  const error = root.querySelector("[data-verification-error]");
  error.textContent = session.saveError || session.error;
  error.hidden = !error.textContent;
  const locked = session.isLocked();
  const verified = session.status === "verified" && session.revision === session.verifiedRevision;
  root.querySelector('[data-review-action="swap-speakers"]').disabled = !session.canSwapSpeakers();
  const speakerStatus = root.querySelector("[data-speaker-status]");
  speakerStatus.hidden = !session.editedPaths.has("utterances");
  speakerStatus.textContent = speakerStatus.hidden ? "" : verified ? "変更した話者で再検証済みです。"
    : session.status === "verifying" ? "変更した話者で再検証中です…" : "話者を入れ替えました。再検証してください。";
  const emptyChecks = root.querySelector("[data-check-empty]");
  if (emptyChecks) emptyChecks.textContent = verified ? "指摘なし" : "再検証が必要です";
  const verify = root.querySelector('[data-review-action="verify"]');
  verify.disabled = session.status === "verifying" || locked;
  verify.textContent = session.status === "verifying" ? "検証中…" : "再検証";
  const confirm = root.querySelector('[data-review-action="confirm"]');
  confirm.disabled = session.saveStatus === "saving" || (!session.canRetrySave() && !gate.ready);
  confirm.textContent = session.saveStatus === "saving" ? "保存中…" : session.canRetrySave() ? "再送" : "確定";
  root.querySelector('[data-review-action="discard"]').disabled = session.saveStatus === "saving";
  for (const field of root.querySelectorAll("[data-review-field]")) {
    let path;
    if (field.dataset.reviewField === "vital" && field.dataset.vitalIndex !== "") path = `vitals[${field.dataset.vitalIndex}]`;
    if (field.dataset.reviewField === "soap" && ["S", "O"].includes(field.dataset.part)) {
      path = `soap.${field.dataset.part}[${field.dataset.sentenceIndex}]`;
    }
    path ??= field.dataset.path;
    field.disabled = locked || Boolean(path && session.action(path) === "delete")
      || (field.dataset.reviewField === "request-urgency" && session.target(path)?.added_by !== "nurse")
      || (field.dataset.reviewField === "evidence" && !field.checked && (session.target(path)?.evidence.length ?? 0) >= 3);
  }
  for (const button of root.querySelectorAll('[data-review-action="add-entry"], [data-review-action="remove-entry"]')) {
    button.disabled = locked || button.dataset.limitReached === "true";
  }
  for (const field of root.querySelectorAll(".vital-field")) {
    field.classList.toggle("is-missing", missing.includes(field.dataset.vitalItem));
    const input = field.querySelector("input");
    const index = input.dataset.vitalIndex;
    const vital = index === "" ? null : session.draft.vitals[Number(index)];
    field.dataset.checkPath = index === "" ? "" : `vitals[${index}]`;
    if (vital?.source === "manual") field.querySelector("[data-vital-evidence]")?.remove();
  }
  for (const button of root.querySelectorAll("[data-split-action]")) {
    if (button.dataset.splitAction === "open") button.disabled = !session.canSplitSentence(button.dataset.splitPath);
    if (button.dataset.splitAction === "undo") button.disabled = !session.canUndoSplit(button.dataset.splitPath);
    if (button.dataset.splitAction === "commit") button.disabled ||= !session.canSplitSentence(button.dataset.splitPath);
    if (button.dataset.splitAction === "cancel") button.disabled = locked;
  }
  for (const field of root.querySelectorAll('[data-review-field="care-plan"], [data-review-field="split-text"]')) {
    field.disabled ||= session.status === "verifying";
  }
  for (const node of root.querySelectorAll("[data-check-path]")) refreshCheckTarget(node, session);

  for (const card of root.querySelectorAll("[data-alert-path]")) {
    const path = card.dataset.alertPath;
    card.dataset.level = verified ? (session.checks.some((check) => check.path === path && check.level === "stop") ? "stop" : "warn") : "pending";
    card.classList.toggle("is-decided", Boolean(session.action(path)));
    if (card.dataset.level === "pending") card.querySelector(".alert-level").textContent = "再検証待ち";
    else if (card.dataset.level === "stop") {
      card.querySelector(".alert-level").textContent = session.action(path) === "keep" ? "要確認・残す選択済み"
        : session.action(path) === "delete" ? "削除予定" : "要確認";
    } else card.querySelector(".alert-level").textContent = "注意";
    for (const button of card.querySelectorAll("[data-decision]")) {
      button.disabled = locked || !verified;
      button.setAttribute("aria-pressed", String(session.action(path) === button.dataset.decision));
    }
    const confirm = card.querySelector('[data-review-action="confirm-multiple"]');
    if (confirm) {
      const checked = session.multipleConfirmed.get(path) === session.fingerprint(path);
      confirm.textContent = checked ? "この値を確認しました" : "この値を使用";
      confirm.setAttribute("aria-pressed", String(checked));
      confirm.disabled = locked || !verified || session.action(path) === "delete";
    }
  }
}
