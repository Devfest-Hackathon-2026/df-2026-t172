import { DEMO_TASK_ASSIGNEES } from "./task-assignment.js";

export const screens = Object.freeze({
  home: "ホーム",
  history: "会話記録",
  tasks: "タスク",
});

const emptyHistory = () => ({
  records: [], patients: [], patientId: "", status: "idle", error: "",
  recordId: null, record: null, detailStatus: "idle", detailError: "",
});

// 患者情報・録音・下書きは、今後も永続ストレージには保持しません。
const state = {
  screen: "home",
  mode: null,
  connection: "pending",
  authentication: "required",
  tasks: [],
  taskStatus: "idle",
  taskError: "",
  pendingTaskIds: [],
  taskView: "open",
  taskPatientId: "",
  taskErrors: {},
  localTaskAssignments: new Map(),
  selectedPatient: null,
  consentConfirmed: false,
  firstSpeaker: "auto",
  inputMethod: "audio",
  transcript: "",
  phase: "idle",
  review: null,
  recorder: null,
  draftError: "",
  draftErrorCode: "",
  confirmedRecord: null,
  history: emptyHistory(),
};

export function getState() {
  return {
    ...state,
    tasks: [...state.tasks],
    pendingTaskIds: [...state.pendingTaskIds],
    taskErrors: { ...state.taskErrors },
    localTaskAssignments: new Map(state.localTaskAssignments),
    selectedPatient: state.selectedPatient ? { ...state.selectedPatient } : null,
    history: { ...state.history, records: [...state.history.records], patients: [...state.history.patients] },
  };
}

export function setTaskState({ tasks, status, error, pendingIds, view, patientId, errors } = {}) {
  if (tasks !== undefined) state.tasks = [...tasks];
  if (status !== undefined) state.taskStatus = status;
  if (error !== undefined) state.taskError = error;
  if (pendingIds !== undefined) state.pendingTaskIds = [...pendingIds];
  if (view !== undefined) state.taskView = view === "done" ? "done" : "open";
  if (patientId !== undefined) state.taskPatientId = patientId;
  if (errors !== undefined) state.taskErrors = { ...errors };
}

export function selectPatient(patient) {
  state.selectedPatient = patient ? { ...patient } : null;
  state.consentConfirmed = false;
  state.firstSpeaker = "auto";
}

export function setLocalTaskAssignment(taskId, assignee) {
  if (state.taskStatus !== "ready" || state.pendingTaskIds.includes(taskId)
    || !state.tasks.some((task) => task.id === taskId && task.status === "open")
    || !DEMO_TASK_ASSIGNEES.some((option) => option.value === assignee)) return false;
  if (assignee) state.localTaskAssignments.set(taskId, assignee);
  else state.localTaskAssignments.delete(taskId);
  return true;
}

export function setFirstSpeaker(value) {
  if (["auto", "nurse", "patient"].includes(value)) state.firstSpeaker = value;
}

export function setTranscript(value) {
  state.transcript = value;
}

export function openTextInput() {
  state.recorder?.dispose();
  state.recorder = null;
  state.inputMethod = "text";
  state.phase = "text-input";
  state.draftError = "";
  state.draftErrorCode = "";
}

export function confirmConsent() {
  if (!state.selectedPatient) return false;
  state.consentConfirmed = true;
  return true;
}

export function clearPatientData() {
  clearReview();
  clearHistory();
  selectPatient(null);
  state.localTaskAssignments.clear();
  setTaskState({ tasks: [], status: "idle", error: "", pendingIds: [], view: "open", patientId: "", errors: {} });
}

export function setHistoryState(patch) {
  state.history = { ...state.history, ...patch };
}

export function clearHistory() {
  state.history = emptyHistory();
}

export function setDraftPhase(phase, error = "", errorCode = "") {
  state.phase = phase;
  state.draftError = error;
  state.draftErrorCode = errorCode;
}

export function setReview(review) {
  state.review?.dispose();
  state.recorder?.dispose();
  state.recorder = null;
  state.transcript = "";
  state.review = review;
  state.firstSpeaker = "auto";
  state.phase = "review";
  state.draftError = "";
  state.draftErrorCode = "";
}

export function clearReview() {
  state.review?.dispose();
  state.recorder?.dispose();
  state.recorder = null;
  state.review = null;
  state.phase = "idle";
  state.draftError = "";
  state.draftErrorCode = "";
  state.confirmedRecord = null;
  state.transcript = "";
  state.inputMethod = "audio";
  state.firstSpeaker = "auto";
}

export function setRecorder(recorder) {
  state.recorder?.dispose();
  state.recorder = recorder;
  state.inputMethod = "audio";
  state.transcript = "";
  state.phase = "mic-request";
  state.draftError = "";
  state.draftErrorCode = "";
}

export function setConfirmedRecord(record) {
  clearReview();
  selectPatient(null);
  state.confirmedRecord = {
    mode: record.mode,
    record_id: record.record_id,
    chart_text: record.chart_text,
    tasks_created: [...record.tasks_created],
    details: null,
    detailStatus: "loading",
    detailError: "",
  };
  state.phase = "export";
}

export function setExportState(recordId, { record, status, error } = {}) {
  if (state.confirmedRecord?.record_id !== recordId) return;
  if (record !== undefined) {
    if (!record || record.record_id !== recordId || record.chart_text !== state.confirmedRecord.chart_text) return;
    state.confirmedRecord.details = record;
  }
  if (status !== undefined) state.confirmedRecord.detailStatus = status;
  if (error !== undefined) state.confirmedRecord.detailError = error;
}

export function setScreen(screen) {
  state.screen = Object.hasOwn(screens, screen) ? screen : "home";
}

export function setAuthentication(status) {
  state.authentication = ["required", "checking", "ready"].includes(status) ? status : "required";
}

export function setConnection(mode) {
  if (mode !== "mock" && mode !== "live") {
    state.mode = null;
    state.connection = "offline";
    return;
  }
  state.mode = mode;
  state.connection = "connected";
}
