import { ApiError, getAllTasks, getOpenTasks, patchTask } from "./api.js?v=20261109-local-category";
import { reportedBy } from "./assignment.js";

export const taskGroups = Object.freeze([
  { value: "said_urgent", label: "急ぎと言われた" },
  { value: "timed", label: "時間指定あり" },
  { value: "none", label: "その他" },
]);

export function taskCategory(task) {
  return task.category ?? "その他";
}

// 既存APIの受け付ける値（backend/app/models/labels.py）に合わせた画面用の選択肢。
// 分類一覧APIは追加せず、保存には既存の PATCH /api/tasks/{id} を使います。
const taskCategories = Object.freeze([
  "物品", "食事", "排泄", "移動", "付き添い", "清潔", "着替え", "体調",
  "痛みの訴え", "医師への確認", "その他",
]);

export async function loadTaskCategories() {
  return [...taskCategories];
}

function validateTask(task) {
  return task && ["id", "patient_id", "room", "name", "text", "created_at"].every((key) => typeof task[key] === "string")
    && /^[A-Za-z0-9_-]{1,40}$/.test(task.id) && /^[A-Za-z0-9_-]{1,40}$/.test(task.patient_id)
    && (task.full_name === undefined || typeof task.full_name === "string")
    && (task.category === undefined || (typeof task.category === "string" && Boolean(task.category.trim()) && task.category.length <= 40))
    && Number.isFinite(Date.parse(task.created_at))
    && (task.done_at == null || (typeof task.done_at === "string" && Number.isFinite(Date.parse(task.done_at))))
    && taskGroups.some((group) => group.value === task.urgency)
    && ["open", "done"].includes(task.status)
    && (task.assigned_to == null || typeof task.assigned_to === "string")
    && (task.assigned_reported_by == null || typeof task.assigned_reported_by === "string")
    && (task.cue == null || (["時間指定", "患者が急ぎと言った"].includes(task.cue.kind) && typeof task.cue.text === "string"))
    && (!task.patient_words || (Array.isArray(task.patient_words)
      && task.patient_words.every((words) => typeof words === "string")));
}

function validateTasks(tasks) {
  if (tasks.some((task) => !validateTask(task)) || new Set(tasks.map((task) => task.id)).size !== tasks.length) {
    throw new ApiError("タスクを読み取れませんでした。", { code: "invalid_response" });
  }
  return tasks;
}

export function groupOpenTasks(tasks) {
  const open = tasks.filter((task) => task.status === "open")
    .sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
  return taskGroups.map((group) => ({
    ...group,
    tasks: open.filter((task) => task.urgency === group.value),
  }));
}

export async function loadOpenTasks(options = {}) {
  const { tasks } = await getOpenTasks(options);
  return validateTasks(tasks).filter((task) => task.status === "open");
}

export async function loadTasks(options = {}) {
  const { tasks } = await getAllTasks(options);
  return validateTasks(tasks);
}

const roomOrder = new Intl.Collator("ja", { numeric: true });

export function taskPatients(tasks) {
  return [...new Map(tasks.map(({ patient_id, room, name, full_name }) => [patient_id, { id: patient_id, room, name, full_name }])).values()]
    .sort((a, b) => roomOrder.compare(a.room, b.room) || roomOrder.compare(a.name, b.name));
}

export function visibleTasks(tasks, { patientId = "", view = "open" } = {}) {
  return tasks.filter((task) => task.status === view && (!patientId || task.patient_id === patientId))
    .sort((a, b) => view === "done"
      ? Date.parse(b.done_at ?? b.created_at) - Date.parse(a.done_at ?? a.created_at)
      : taskGroups.findIndex((group) => group.value === a.urgency) - taskGroups.findIndex((group) => group.value === b.urgency)
        || Date.parse(a.created_at) - Date.parse(b.created_at));
}

async function updateTask(task, changes, options) {
  const { task: updated } = await patchTask(task.id, changes, options);
  // reported_by は送るだけの欄（返りは assigned_reported_by）なので、突き合わせから外します
  const applied = Object.entries(changes).filter(([key]) => key !== "reported_by");
  if (!validateTask(updated) || updated.patient_id !== task.patient_id
    || applied.some(([key, value]) => updated[key] !== value)) {
    throw new ApiError("タスクの更新結果を読み取れませんでした。", { code: "invalid_response" });
  }
  return updated;
}

export function changeTaskUrgency(task, { urgency, ...options } = {}) {
  if (!taskGroups.some((group) => group.value === urgency)) {
    throw new ApiError("タスクの区分が正しくありません。", { code: "invalid_urgency" });
  }
  return updateTask(task, { urgency }, options);
}

export function changeTaskCategory(task, { category, ...options } = {}) {
  if (typeof category !== "string" || !category.trim() || category.length > 40) {
    throw new ApiError("タスクの種類が正しくありません。", { code: "invalid_category" });
  }
  return updateTask(task, { category }, options);
}

/** 区分・分類・担当をまとめて変えます。担当（assignedTo）は看護師の一覧の id（S-08）。 */
export function changeTaskDetails(task, { urgency, category, assignedTo, ...options } = {}) {
  const changes = {};
  if (urgency !== undefined) {
    if (!taskGroups.some((group) => group.value === urgency)) {
      throw new ApiError("タスクの区分が正しくありません。", { code: "invalid_urgency" });
    }
    changes.urgency = urgency;
  }
  if (category !== undefined) {
    if (typeof category !== "string" || !category.trim() || category.length > 40) {
      throw new ApiError("タスクの種類が正しくありません。", { code: "invalid_category" });
    }
    changes.category = category;
  }
  if (assignedTo !== undefined) {
    if (typeof assignedTo !== "string" || !/^[A-Za-z0-9_-]{1,40}$/.test(assignedTo)) {
      throw new ApiError("担当の指定が正しくありません。", { code: "invalid_nurse" });
    }
    changes.assigned_to = assignedTo;
  }
  if (!Object.keys(changes).length) {
    throw new ApiError("変更する項目がありません。", { code: "invalid_task_changes" });
  }
  // 担当を変えるときは、画面で選んだ「自分」を変えた人の自己申告として送ります（選んでいなければ送りません）
  return updateTask(task, { ...changes, ...(changes.assigned_to ? reportedBy() : {}) }, options);
}

export function completeTask(task, options = {}) {
  return updateTask(task, { status: "done" }, options);
}

export function reopenTask(task, options = {}) {
  return updateTask(task, { status: "open" }, options);
}
