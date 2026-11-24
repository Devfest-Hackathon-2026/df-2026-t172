import { nurseName } from "../assignment.js?v=20261121-context-help";
import { displayName } from "../patients.js?v=20261121-context-help";
import { vitalItems } from "../records.js?v=20261121-context-help";
import { savedTarget } from "../history.js?v=20261121-context-help";
import { renderEvidence } from "./evidence-card.js";
import { element, panel } from "./review-dom.js";

const dateTime = new Intl.DateTimeFormat("ja-JP", {
  timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});

const urgencyLabels = { said_urgent: "急ぎ", timed: "時間指定", none: "その他" };

/** 保存された各項目をそのまま表示し、カルテ文の解析や数値の補正は行いません。 */
export function renderRecordSummary(record, { showEvidence = false, patientHeading = "h2" } = {}) {
  const view = element("div", "record-summary");
  const meta = element("header", "saved-record-meta");
  meta.append(element(patientHeading, "record-card-name", displayName(record)),
    element("span", "patient-room", `${record.room}号室${record.bed ? ` ${record.bed}` : ""}`));
  if (record.created_at) {
    const time = element("time", "", dateTime.format(new Date(record.created_at)));
    time.dateTime = record.created_at;
    meta.append(time);
  }
  view.append(meta);
  if (record.confirmed_reported_by) {
    // ログインがないので、画面で選んだ「自分」の自己申告です（本人の確かめはありません、S-08）
    const who = nurseName(record.confirmed_reported_by) || record.confirmed_reported_by;
    view.append(element("p", "saved-check-note", `確定した人：${who}（自己申告）`));
  }
  const evidenceSession = { utterances: record.evidence_utterances ?? [], audioUrl: null, recordEvidenceTap() {} };
  const appendEvidence = (node, item, key) => {
    if (showEvidence && item.evidence.length) node.append(renderEvidence(item.evidence, evidenceSession, key));
  };
  const amended = new Set(record.amended_paths);
  const appendAmended = (node, path) => {
    if (amended.has(path)) node.append(element("p", "record-request-meta", "手動で編集"));
  };

  const vitals = panel("バイタル");
  vitals.classList.add("record-vitals-panel");
  const grid = element("dl", "record-vitals");
  for (const [index, vital] of record.vitals.entries()) {
    const field = element("div", "record-vital");
    field.append(element("dt", "", vital.item));
    const value = element("dd");
    value.append(element("span", "record-vital-value", vital.value || "—"));
    const unit = vitalItems.find((definition) => definition.item === vital.item)?.unit;
    if (unit && !vital.value.trim().endsWith(unit)) value.append(element("span", "record-vital-unit", unit));
    field.append(value);
    appendEvidence(value, vital, `saved-vital-${index}`);
    appendAmended(value, `vitals[${index}]`);
    grid.append(field);
  }
  vitals.append(record.vitals.length ? grid : element("p", "record-empty", "—"));
  view.append(vitals);

  const planLabels = new Map((record.care_plans ?? []).map(({ id, label }) => [id, label]));
  const hasAssignedPlan = [...record.soap.S, ...record.soap.O].some((sentence) => planLabels.has(sentence.plan_id));
  for (const [part, title] of [["S", "患者の訴え"], ["O", "観察・測定"], ["A", "アセスメント"], ["P", "計画"]]) {
    const section = element("section", "record-soap-section");
    section.dataset.soapPart = part;
    const heading = element("h2", "record-soap-heading");
    heading.append(element("span", "record-soap-letter", part), document.createTextNode(title));
    section.append(heading);
    const sentences = ["S", "O"].includes(part) ? record.soap[part] : [{ text: record.soap[part], evidence: [] }];
    if (!sentences.some((sentence) => sentence.text.trim())) {
      section.append(element("p", "record-empty", "—"));
      if (part === "A" || part === "P") appendAmended(section, `soap.${part}`);
    }
    for (const [index, sentence] of sentences.entries()) {
      if (!sentence.text.trim()) continue;
      const row = element("div", "record-sentence");
      row.append(element("p", "record-body", sentence.text));
      if (hasAssignedPlan && ["S", "O"].includes(part)) {
        row.append(element("p", "record-request-meta", planLabels.get(sentence.plan_id) ?? "計画外"));
      }
      appendEvidence(row, sentence, `saved-soap-${part}-${index}`);
      appendAmended(row, part === "A" || part === "P" ? `soap.${part}` : `soap.${part}[${index}]`);
      section.append(row);
    }
    view.append(section);
  }

  if (record.patient_check?.note) view.append(element("p", "saved-check-note", record.patient_check.note));
  if (record.kept_after_check?.length) {
    const section = panel("確認して残した内容");
    for (const check of record.kept_after_check) {
      const row = element("div", "record-sentence");
      row.append(element("p", "record-body", savedTarget(record, check.path) || "確認した内容"));
      section.append(row);
    }
    view.append(section);
  }
  for (const [key, title] of [["requests", "患者からの依頼"], ["doctor_questions", "医師への確認"], ["manual_needed", "手で入力が必要（薬など）"]]) {
    if (!record[key].length) continue;
    const section = panel(title);
    if (key === "requests") {
      section.append(element("p", "record-request-meta", "緊急度はAIの判断ではありません。"));
    }
    for (const [index, item] of record[key].entries()) {
      const row = element("div", "record-sentence");
      row.append(element("p", "record-body", item.text));
      if (key === "requests") {
        row.append(element("p", "record-request-meta",
          `緊急度：${urgencyLabels[item.urgency]}　分類：${item.category ?? "その他"}　職種：${item.role ?? "その他"}`));
      }
      appendEvidence(row, item, `saved-${key}-${index}`);
      appendAmended(row, `${key}[${index}]`);
      if (item.cue && showEvidence) {
        const cue = element("div", "record-cue");
        cue.append(element("p", "record-body", item.cue.text));
        appendEvidence(cue, item.cue, `saved-cue-${index}`);
        row.append(cue);
      }
      section.append(row);
    }
    view.append(section);
  }
  return view;
}

/** 通常の表示は構造化した記録。コピーに失敗した場合だけ原文を選択可能にします。 */
export function renderCopyFallback(chartText) {
  const details = element("details", "record-copy-fallback");
  details.hidden = true;
  details.dataset.copyFallback = "";
  details.append(element("summary", "evidence-toggle", "コピー用の文章"));
  const output = element("textarea", "record-output");
  output.readOnly = true;
  output.rows = 8;
  output.value = chartText;
  output.setAttribute("aria-label", "カルテ用の文章");
  details.append(output);
  return details;
}
