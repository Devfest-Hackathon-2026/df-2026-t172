import { getAssigneeTable, getMyNurseId, getNurses, getTaskScope, nurseName } from "../assignment.js";
import { displayName } from "../patients.js";
import { element } from "./review-dom.js";

/** タスクの箱に出す担当の名前（S-08）。看護師の一覧が読めなければ出しません。 */
export function renderTaskAssignee(task) {
  if (!getNurses().length) return null;
  return element("span", "task-assignee", `担当：${nurseName(task.assigned_to) || "未定"}`);
}

/** 「タスクを変更」の担当の欄の選択肢。自分を選んでいれば「（自分）」を付けます。 */
export function taskAssigneeOptions(task) {
  const nurses = getNurses();
  const me = getMyNurseId();
  const options = nurses.map(({ id, name }) => ({ value: id, label: id === me ? `${name}（自分）` : name }));
  if (options.length && !nurses.some((nurse) => nurse.id === task.assigned_to)) {
    options.unshift({ value: "", label: "未定" });
  }
  return options;
}

/** 担当の欄の下の注意書き。最後に変えた人（自己申告）と、「自分」を選ぶと残ることを伝えます。 */
export function taskAssigneeNote(task) {
  const lines = [];
  if (task.assigned_set_by === "nurse") {
    const who = nurseName(task.assigned_reported_by) || "不明（「自分」が選ばれていなかった）";
    lines.push(`最後に担当を変えた人：${who}（自己申告）`);
  }
  if (!getMyNurseId()) lines.push("一覧の上の「自分」で名前を選ぶと、変えた人として残ります（自己申告）");
  return lines.join("\n");
}

/** 「自分」の名前を選ぶ欄と、「全部／自分の担当」の切り替え。看護師の一覧がなければ出しません。 */
export function renderTaskScope() {
  const nurses = getNurses();
  if (!nurses.length) return null;
  const me = getMyNurseId();
  const wrap = element("div", "task-scope");
  const label = element("label", "task-scope-label", "自分");
  label.htmlFor = "task-my-nurse";
  const select = element("select", "input task-scope-select");
  select.id = "task-my-nurse";
  const none = element("option", "", "名前を選ぶ");
  none.value = "";
  select.append(none);
  for (const nurse of nurses) {
    const option = element("option", "", nurse.name);
    option.value = nurse.id;
    select.append(option);
  }
  select.value = me;

  const scope = getTaskScope();
  const switcher = element("div", "task-view-switch task-scope-switch");
  switcher.setAttribute("role", "group");
  switcher.setAttribute("aria-label", "表示するタスク");
  for (const [value, text] of [["all", "全部"], ["mine", "自分の担当"]]) {
    const button = element("button", "task-view-button", text);
    button.type = "button";
    button.dataset.taskScope = value;
    button.disabled = value === "mine" && !me;
    button.setAttribute("aria-pressed", String(scope === value));
    switcher.append(button);
  }
  wrap.append(label, select, switcher);
  return wrap;
}

function assigneeRow(patient, nurses, pendingPatientId) {
  const row = element("div", "assignee-row");
  const label = element("label", "assignee-patient", `${patient.room}号室　${displayName(patient)}`);
  label.htmlFor = `assignee-${patient.id}`;
  const select = element("select", "input assignee-select");
  select.id = `assignee-${patient.id}`;
  select.dataset.patientAssignee = patient.id;
  if (!nurses.some((nurse) => nurse.id === patient.assigned_to)) {
    const none = element("option", "", "未定");
    none.value = "";
    select.append(none);
  }
  for (const nurse of nurses) {
    const option = element("option", "", nurse.name);
    option.value = nurse.id;
    select.append(option);
  }
  select.value = patient.assigned_to ?? "";
  select.disabled = Boolean(pendingPatientId);
  row.append(label, select);
  return row;
}

/** 患者ごとの基本の受け持ちの表（その日の入れ替え用）。開くまでは見出しのボタンだけを出します。 */
export function renderAssigneeTable() {
  const nurses = getNurses();
  const { patients, open, pendingPatientId } = getAssigneeTable();
  if (!nurses.length || !patients.length) return null;
  const section = element("section", "assignee-table");
  const toggle = element("button", "secondary-button assignee-toggle", open ? "受け持ちの表を閉じる" : "受け持ちを変える");
  toggle.type = "button";
  toggle.id = "assignee-toggle";
  toggle.dataset.action = "toggle-assignees";
  toggle.setAttribute("aria-expanded", String(open));
  section.append(toggle);
  if (!open) return section;
  section.append(element("p", "assignee-note",
    "受け持ちを変えると、まだ誰も担当を変えていない未完了のタスクも新しい受け持ちに移ります。"));
  for (const patient of patients) section.append(assigneeRow(patient, nurses, pendingPatientId));
  return section;
}
