import { ApiError, request } from "./api.js";
import { loadPatients } from "./patients.js";

// タスクの担当の割り振り（決まり S-08）。ログインはないので、「自分」は看護師が一度選んで
// 合言葉と同じく sessionStorage に置くだけです（タブを閉じると消えます）。
const MY_NURSE_KEY = "nursenote.my-nurse";
const SCOPE_KEY = "nursenote.task-scope";
const ID_PATTERN = /^[A-Za-z0-9_-]{1,40}$/;

let nurses = [];

function readStored(key) {
  try {
    return window.sessionStorage.getItem(key) || "";
  } catch {
    return "";
  }
}

function writeStored(key, value) {
  try {
    if (value) window.sessionStorage.setItem(key, value);
    else window.sessionStorage.removeItem(key);
  } catch {
    // 保存先を使えなくても、この画面を開いている間の切り替えは続けられます。
  }
}

function isNurse(nurse) {
  return nurse && ID_PATTERN.test(nurse.id) && typeof nurse.name === "string" && typeof nurse.kana === "string";
}

/** 看護師の一覧を1回だけ読みます。読めなければ空のまま（担当の表示を出さないだけにします）。 */
export async function ensureNurses(options = {}) {
  if (nurses.length) return nurses;
  try {
    const data = await request("/api/nurses", { ...options, timeoutMs: 10000 });
    if (Array.isArray(data.nurses) && data.nurses.every(isNurse)) {
      nurses = data.nurses.map(({ id, name, kana }) => ({ id, name, kana }));
    }
  } catch {
    // 担当の機能がないサーバーでも、タスクの一覧はこれまでどおり使えるようにします。
  }
  return nurses;
}

export function getNurses() {
  return [...nurses];
}

export function nurseName(nurseId) {
  return nurses.find((nurse) => nurse.id === nurseId)?.name ?? "";
}

export function getMyNurseId() {
  const id = readStored(MY_NURSE_KEY);
  return nurses.some((nurse) => nurse.id === id) ? id : "";
}

export function setMyNurseId(nurseId) {
  writeStored(MY_NURSE_KEY, nurses.some((nurse) => nurse.id === nurseId) ? nurseId : "");
}

/** 「全部」か「自分の担当だけ」か。自分を選んでいなければ常に「全部」です。 */
export function getTaskScope() {
  return readStored(SCOPE_KEY) === "mine" && getMyNurseId() ? "mine" : "all";
}

export function setTaskScope(scope) {
  writeStored(SCOPE_KEY, scope === "mine" ? "mine" : "");
}

/** 変えた人・確定した人の自己申告として送る欄（「自分」を選んでいなければ空）。本人の確かめはありません。 */
export function reportedBy() {
  const me = getMyNurseId();
  return me ? { reported_by: me } : {};
}

export function scopedTasks(tasks) {
  if (getTaskScope() !== "mine") return tasks;
  const me = getMyNurseId();
  return tasks.filter((task) => task.assigned_to === me);
}

// 患者の基本の受け持ち（その日に入れ替える）。名簿は電子カルテの持ち物なので、受け持ちだけを変えます。
let patients = [];
let assigneeTableOpen = false;
let pendingPatientId = "";

/** 名簿（受け持ちつき）を読み直します。読めなければ前の分のままにします。 */
export async function loadAssignees(options = {}) {
  try {
    patients = await loadPatients(options);
  } catch {
    // 受け持ちの表が古いままになるだけで、タスクの一覧は使えます。
  }
  return patients;
}

export function getAssigneeTable() {
  return { patients: [...patients], open: assigneeTableOpen, pendingPatientId };
}

export function toggleAssigneeTable() {
  assigneeTableOpen = !assigneeTableOpen;
}

/** 受け持ちを変えます。担当を人が変えていない未完了のタスクも、サーバーが一緒に移します。 */
export async function changePatientAssignee(patientId, nurseId, options = {}) {
  pendingPatientId = patientId;
  try {
    const data = await request(`/api/patients/${encodeURIComponent(patientId)}`, {
      ...options, method: "PATCH", body: { assigned_to: nurseId, ...reportedBy() },
    });
    if (data.patient?.id !== patientId || data.patient.assigned_to !== nurseId || !Array.isArray(data.tasks_moved)) {
      throw new ApiError("受け持ちの変更結果を読み取れませんでした。", { code: "invalid_response" });
    }
    patients = patients.map((patient) => patient.id === patientId ? { ...patient, assigned_to: nurseId } : patient);
    return { moved: data.tasks_moved.length };
  } finally {
    pendingPatientId = "";
  }
}
