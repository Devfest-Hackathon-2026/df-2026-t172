import { element, reviewButton } from "./review-dom.js";
import { renderEvidence, utteranceLabel } from "./evidence-card.js";
import { taskGroups } from "../tasks.js";

export function markCheckTarget(node, path) {
  node.dataset.checkPath = path ?? "";
  const heading = element("div", "check-heading");
  const marker = element("span", "check-marker");
  marker.dataset.checkMarker = "";
  marker.hidden = true;
  const details = reviewButton("理由・対応を見る", "show-check", "text-button check-details-button");
  details.hidden = true;
  heading.hidden = true;
  heading.append(marker, details);
  node.append(heading);
}

export function refreshCheckTarget(node, session) {
  const path = node.dataset.checkPath;
  const level = path ? session.checkLevel(path) : "clear";
  node.dataset.checkLevel = level;
  node.dataset.checkAction = level === "stop" ? session.action(path) ?? "" : "";
  const marker = node.querySelector("[data-check-marker]");
  const heading = node.querySelector(".check-heading");
  const details = heading.querySelector('[data-review-action="show-check"]');
  heading.hidden = level === "clear";
  marker.hidden = level === "clear";
  marker.id = path ? `check-marker-${path}` : "";
  marker.textContent = level === "pending" ? "未検証"
    : level === "warn" ? "注意"
      : session.action(path) === "keep" ? "要確認・残す選択済み"
        : session.action(path) === "delete" ? "削除予定" : "要確認";
  details.hidden = !["stop", "warn"].includes(level) || !session.checks.some((check) => check.path === path);
  details.dataset.path = path ?? "";
  details.dataset.focusKey = `show-check-${path}`;
  details.setAttribute("aria-controls", `check-${path}`);
  for (const input of node.querySelectorAll("textarea, input:not([type=checkbox])")) {
    input.setAttribute("aria-invalid", String(level === "stop"));
    const descriptions = (input.getAttribute("aria-describedby") ?? "").split(/\s+/u)
      .filter((id) => id && !id.startsWith("check-marker-"));
    if (level !== "clear") descriptions.push(marker.id);
    if (descriptions.length) input.setAttribute("aria-describedby", descriptions.join(" "));
    else input.removeAttribute("aria-describedby");
  }
}

export function addEntryButton(kind, label, session) {
  const button = reviewButton(label, "add-entry", "text-button add-entry");
  button.dataset.kind = kind;
  button.dataset.focusKey = `add-${kind}`;
  const list = kind.startsWith("soap.") ? session.draft.soap[kind.slice(-1)] : session.draft[kind];
  button.dataset.limitReached = String(list.length >= (kind.startsWith("soap.") ? 50 : 30));
  return button;
}

function evidencePicker(item, path, session) {
  const details = element("details", "evidence-details evidence-picker");
  details.dataset.detailsKey = `choose-${path}`;
  details.append(element("summary", "evidence-toggle", `根拠を選択（${item.evidence.length}/3）`));
  if (!session.utterances.length) details.append(element("p", "empty-inline", "選択できる発言はありません"));
  const speakers = { nurse: "看護師", patient: "患者", unknown: "話者不明" };
  for (const utterance of session.utterances) {
    const label = element("label", "evidence-choice");
    const checkbox = element("input");
    checkbox.type = "checkbox";
    checkbox.checked = item.evidence.includes(utterance.id);
    checkbox.dataset.reviewField = "evidence";
    checkbox.dataset.path = path;
    checkbox.dataset.utteranceId = utterance.id;
    checkbox.dataset.focusKey = `choose-${path}-${utterance.id}`;
    checkbox.setAttribute("aria-label", `${utteranceLabel(utterance.id)}、${speakers[utterance.speaker]}：${utterance.text}`);
    const text = element("span");
    text.append(element("span", "utterance-meta", `${utteranceLabel(utterance.id)}　${speakers[utterance.speaker]}`),
      element("span", "utterance-text", utterance.text));
    label.append(checkbox, text);
    details.append(label);
  }
  return details;
}

export function renderReviewEntry(item, path, session, { part, index, evidenceKey, label, className = "review-information" } = {}) {
  const row = element("div", className);
  row.dataset.sentencePath = path;
  markCheckTarget(row, path);
  const heading = element("div", "entry-heading");
  if (session.addedElements.has(item)) {
    const remove = reviewButton("削除", "remove-entry", "text-button danger-text");
    remove.dataset.path = path;
    remove.dataset.focusKey = `remove-${path}`;
    remove.setAttribute("aria-label", `${label}の追加項目を削除`);
    heading.append(remove);
  }
  const input = element("textarea", "textarea");
  input.value = item.text;
  input.maxLength = 5000;
  input.rows = 2;
  input.dataset.reviewField = part ? "soap" : "element";
  input.dataset.path = path;
  input.dataset.focusKey = part ? `soap-${part}-${index}` : `entry-${path}`;
  if (part) {
    input.dataset.part = part;
    input.dataset.sentenceIndex = String(index);
  }
  input.setAttribute("aria-label", label);
  if (heading.childElementCount) row.append(heading);
  row.append(input);
  if (path.startsWith("requests[")) {
    if (session.addedElements.has(item)) {
      const selectLabel = element("label", "form-label", "区分");
      const select = element("select", "input entry-urgency");
      select.dataset.reviewField = "request-urgency";
      select.dataset.path = path;
      select.dataset.requestIndex = String(index);
      select.dataset.focusKey = `urgency-${path}`;
      select.setAttribute("aria-label", `${label}の区分`);
      for (const group of taskGroups) {
        const option = element("option", "", group.label);
        option.value = group.value;
        select.append(option);
      }
      select.value = item.urgency;
      selectLabel.append(select);
      row.append(selectLabel);
    }
    if (item.cue) {
      const cue = element("div", "request-cue");
      markCheckTarget(cue, `${path}.cue`);
      cue.append(element("p", "request-text", item.cue.text),
        renderEvidence(item.cue.evidence, session, `cue-evidence-${index}`));
      row.append(cue);
    }
  }
  if (session.addedElements.has(item)) row.append(evidencePicker(item, path, session));
  else row.append(renderEvidence(item.evidence, session, evidenceKey));
  if (session.action(path) === "delete") row.append(element("span", "delete-note", "確定時に削除"));
  if (path.startsWith("requests[") && session.action(`${path}.cue`) === "delete") {
    row.append(element("span", "delete-note", "手がかりは確定時に削除"));
  }
  return row;
}
