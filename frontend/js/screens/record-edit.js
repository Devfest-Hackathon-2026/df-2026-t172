import { element, panel } from "../components/review-dom.js";
import { displayName } from "../patients.js?v=20261121-context-help";
import { vitalItems } from "../records.js?v=20261121-context-help";
import { taskCategories, taskGroups } from "../tasks.js?v=20261121-context-help";

const vitalOptions = vitalItems.map(({ item }) => [item, item]);
const urgencyOptions = taskGroups.map(({ value, label }) => [value, label]);
const categoryOptions = taskCategories.map((value) => [value, value]);
const roleOptions = ["看護師", "看護助手", "医師", "その他"].map((value) => [value, value]);

function button(label, className = "secondary-button") {
  const node = element("button", className, label);
  node.type = "button";
  return node;
}

function field(row, label, input) {
  const wrapper = element("label", "record-edit-field");
  wrapper.append(element("span", "", label), input);
  row.append(wrapper);
  return input;
}

function textField(row, label, value, { multiline = true, required = false, maxLength = 5000 } = {}) {
  const input = element(multiline ? "textarea" : "input");
  if (multiline) input.rows = 3;
  input.maxLength = maxLength;
  input.required = required;
  input.value = value;
  return field(row, label, input);
}

function choice(row, label, options, selected) {
  const select = element("select");
  for (const [value, text] of options) {
    const option = element("option", "", text);
    option.value = value;
    select.append(option);
  }
  select.value = selected;
  return field(row, label, select);
}

function editList(title, items, blank, limit, fields, locked = false) {
  const group = panel(title);
  const controls = element("fieldset", "record-edit-rows");
  controls.disabled = locked;
  controls.setAttribute("aria-label", title);
  const list = element("div", "record-edit-list");
  const add = button(`${title}を追加`, "text-button");
  const readers = new Map();

  function append(item, index, focus = false) {
    const row = element("div", "record-edit-row");
    const remove = button("削除", "text-button");
    remove.setAttribute("aria-label", `${title}の項目を削除`);
    readers.set(row, fields(row, item, index));
    row.append(remove);
    list.append(row);
    add.disabled = readers.size >= limit;
    remove.addEventListener("click", () => {
      const next = row.nextElementSibling ?? row.previousElementSibling;
      readers.delete(row);
      row.remove();
      add.disabled = false;
      (next?.querySelector("input, textarea, select") ?? add).focus();
    });
    if (focus) row.querySelector("textarea, input, select").focus();
  }
  items.forEach((item, index) => append(item, index));
  add.addEventListener("click", () => append(blank, null, true));
  controls.append(list, add);
  if (locked) group.append(element("p", "record-request-meta", "タスクとの対応が保存されていないため、この記録の依頼は編集できません。"));
  group.append(controls);

  const values = () => Array.from(readers.values(), (read) => read());
  const original = JSON.stringify(values());
  return { group, read: () => {
    const updated = values();
    return !locked && JSON.stringify(updated) !== original ? updated : undefined;
  } };
}

function populatePreview(record, changes) {
  const { soap, ...groups } = changes;
  return { ...record, ...groups, soap: { ...record.soap, ...soap }, kept_after_check: [], amended_paths: [] };
}

export function createRecordEditor(record, { onReview, onCancel, onReload }) {
  const view = element("section", "record-edit-screen");
  const cancel = button("取り消す", "text-button");
  const form = element("form", "record-edit-form");
  const fields = element("fieldset", "record-edit-fields");
  const status = element("p", "form-error");
  status.hidden = true;
  status.tabIndex = -1;
  status.setAttribute("role", "alert");
  const reload = button("最新の記録を開き直す");
  reload.hidden = true;
  const review = button("変更を確認", "primary-button");
  review.type = "submit";
  cancel.addEventListener("click", onCancel);
  reload.addEventListener("click", onReload);

  const vital = editList("バイタル", record.vitals, { item: vitalOptions[0][0], value: "" }, 30, (row, item, index) => {
    const kind = choice(row, "項目", vitalOptions, item.item);
    const value = textField(row, "測定値", item.value, { multiline: false, required: index === null || Boolean(item.value.trim()), maxLength: 100 });
    return () => ({ index, item: kind.value, value: value.value });
  });

  function soapList(part, title) {
    const plans = [["", "計画外"], ...record.care_plans.map(({ id, label }) => [id, label])];
    return editList(title, record.soap[part], { text: "", plan_id: null }, 50, (row, item, index) => {
      const text = textField(row, "内容", item.text, { required: index === null || Boolean(item.text.trim()) });
      const known = !item.plan_id || plans.some(([id]) => id === item.plan_id);
      const options = known ? plans : [...plans, [item.plan_id, "保存時の看護計画（現在の名簿にありません）"]];
      const plan = choice(row, "看護計画", options, item.plan_id ?? "");
      return () => ({ index, text: text.value, plan_id: plan.value || null });
    });
  }

  const s = soapList("S", "S 患者の訴え");
  const o = soapList("O", "O 観察・測定");
  const assessment = panel("A アセスメント");
  const a = textField(assessment, "アセスメント", record.soap.A);
  const plan = panel("P 計画");
  const p = textField(plan, "計画", record.soap.P);
  const initialA = a.value;
  const initialP = p.value;

  const ids = record.requests.map(({ task_id }) => task_id);
  const requestsLocked = ids.some((id) => !id) || new Set(ids).size !== ids.length;
  const requestBlank = { text: "", task_id: null, urgency: "none", category: "その他", role: "その他" };
  const requests = editList("患者からの依頼", record.requests, requestBlank, 30, (row, item) => {
    const text = textField(row, "依頼内容", item.text, { required: !item.task_id || Boolean(item.text.trim()) });
    const urgency = choice(row, "緊急度", urgencyOptions, item.urgency);
    const category = choice(row, "分類", categoryOptions, item.category);
    const role = choice(row, "対応する職種", roleOptions, item.role);
    return () => ({ task_id: item.task_id, text: text.value, urgency: urgency.value, category: category.value, role: role.value });
  }, requestsLocked);

  function textList(key, title) {
    return editList(title, record[key], { text: "" }, 30, (row, item, index) => {
      const text = textField(row, "内容", item.text, { required: index === null || Boolean(item.text.trim()) });
      return () => ({ index, text: text.value });
    });
  }
  const manual = textList("manual_needed", "手で入力が必要（薬など）");
  const questions = textList("doctor_questions", "医師への確認");

  function changes() {
    const changed = {};
    const soap = {};
    for (const [part, list] of [["S", s], ["O", o]]) {
      const rows = list.read();
      if (rows !== undefined) soap[part] = rows;
    }
    if (a.value !== initialA) soap.A = a.value;
    if (p.value !== initialP) soap.P = p.value;
    if (Object.keys(soap).length) changed.soap = soap;
    for (const [key, list] of [["vitals", vital], ["requests", requests], ["manual_needed", manual], ["doctor_questions", questions]]) {
      const rows = list.read();
      if (rows !== undefined) changed[key] = rows;
    }
    return changed;
  }

  function showError(message, { canReload = false } = {}) {
    status.hidden = !message;
    status.textContent = message;
    reload.hidden = !canReload;
    if (message) status.focus();
  }

  fields.append(vital.group, s.group, o.group, assessment, plan, requests.group, questions.group, manual.group);
  const actions = element("div", "saved-record-actions");
  actions.append(status, reload, review);
  form.append(fields, actions);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (review.disabled) return;
    const updated = changes();
    if (!Object.keys(updated).length) {
      showError("変更された項目はありません。");
      return;
    }
    onReview(updated, populatePreview(record, updated), review);
  });
  view.append(cancel, element("h1", "page-title", "記録を編集"),
    element("p", "patient-room", `${record.room}号室　${displayName(record)}`), form);

  return {
    view,
    hasChanges: () => Object.keys(changes()).length > 0,
    showError,
    setSaving(saving) {
      fields.disabled = review.disabled = cancel.disabled = reload.disabled = saving;
      review.textContent = saving ? "保存中…" : "変更を確認";
      form.setAttribute("aria-busy", String(saving));
    },
  };
}
