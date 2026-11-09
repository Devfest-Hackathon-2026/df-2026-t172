import { AUTH_REQUIRED_EVENT, MODE_EVENT, getHealth, getPatients } from "./api.js";
import { getPasscode, renderAuth, setPasscode } from "./auth.js";
import {
  clearHistory, clearPatientData, clearReview, confirmConsent, getState, openTextInput, screens, selectPatient,
  setAuthentication, setConfirmedRecord, setConnection, setDraftPhase, setExportState, setFirstSpeaker, setHistoryState, setRecorder, setReview, setScreen, setTaskState, setTranscript,
} from "./state.js";
import { renderNavigation, updateNavigation, updateTaskCount } from "./components/navigation.js?v=20261109-count";
import { renderHome, renderHomeTasks } from "./screens/home.js?v=20261110-ainote";
import { createPatientSheet } from "./components/patient-sheet.js";
import { changeTaskDetails, completeTask, loadTaskCategories, loadTasks, reopenTask, taskCategory } from "./tasks.js?v=20261110-assign";
import { createTaskChoiceDialog } from "./components/task-choice-dialog.js?v=20261110-assign";
import {
  changePatientAssignee, ensureNurses, loadAssignees, nurseName, setMyNurseId, setTaskScope, toggleAssigneeTable,
} from "./assignment.js";
import { taskAssigneeNote, taskAssigneeOptions } from "./components/task-assign.js?v=20261110-assign";
import { createAudioReview, createTextReview } from "./records.js";
import { refreshTextInput, renderTextInput } from "./screens/text-input.js";
import { AudioRecorder } from "./recorder.js";
import { refreshRecordingStatus, renderRecording } from "./screens/recording.js";
import { renderProcessing } from "./screens/processing.js";
import { refreshReviewStatus, renderReview } from "./screens/review.js?v=20261110-ainote";
import { refreshExportDetails, renderExport } from "./screens/export.js";
import { loadRecord, loadRecords } from "./history.js";
import { loadPatients } from "./patients.js";
import { renderHistory } from "./screens/history.js?v=20261109-color";
import { renderRecordDetail } from "./screens/record-detail.js";
import { renderTasks, renderTasksContent } from "./screens/tasks.js?v=20261110-ainote";

const content = document.getElementById("screen");
const navigation = document.getElementById("bottom-nav");
const modeBadge = document.getElementById("mode-badge");
const toast = document.getElementById("toast");
let toastTimeout;
let patientSheet;
let taskChoiceDialog;
let taskController;
let sessionVersion = 0;
let draftController;
let historyController;
let exportController;
const taskUpdates = new Map();
let taskRefreshQueued = false;

function fitTextarea(input) {
  input.style.height = "auto";
  input.style.height = `${input.scrollHeight + 2}px`;
}

function fitReviewTextareas() {
  for (const input of content.querySelectorAll("textarea[data-review-field]")) fitTextarea(input);
}

function screenFromHash() {
  const screen = window.location.hash.slice(1);
  if (screen.startsWith("history/")) return "history";
  return Object.hasOwn(screens, screen) ? screen : "home";
}

function recordIdFromHash() {
  return window.location.hash.startsWith("#history/") ? window.location.hash.slice(9) : null;
}

function showToast(message) {
  window.clearTimeout(toastTimeout);
  toast.textContent = message;
  toast.hidden = false;
  toastTimeout = window.setTimeout(() => {
    toast.hidden = true;
    toast.textContent = "";
  }, 3000);
}

function renderScreen({ focus = false } = {}) {
  taskChoiceDialog?.close();
  const { screen, authentication, phase, review, recorder, selectedPatient, draftError, draftErrorCode, confirmedRecord } = getState();
  if (authentication !== "ready") return;
  for (const audio of content.querySelectorAll("audio")) audio.pause();
  navigation.hidden = false;
  let view;
  if (screen === "history") view = getState().history.recordId
    ? renderRecordDetail(getState().history) : renderHistory(getState().history);
  else if (screen === "tasks") view = renderTasks(getState());
  else if (phase === "review" && review) view = renderReview(review);
  else if (phase === "export" && confirmedRecord) view = renderExport(confirmedRecord);
  else if (phase === "text-input") view = renderTextInput(selectedPatient, getState().transcript);
  else if (["mic-request", "recording", "recording-error", "recording-stopped"].includes(phase)) {
    view = renderRecording(selectedPatient, recorder, phase, draftError, draftErrorCode);
  }
  else if (["processing", "draft-error"].includes(phase)) view = renderProcessing(selectedPatient, draftError, getState().inputMethod);
  else view = renderHome(getState());
  content.replaceChildren(view);
  fitReviewTextareas();
  const title = screen === "history" && getState().history.recordId ? "記録の詳細"
    : screen === "home" && phase === "export" ? "記録を確定しました"
    : screen === "home" && phase === "review" ? "記録確認"
    : screen === "home" && phase === "text-input" ? "テキスト入力"
    : screen === "home" && ["mic-request", "recording", "recording-error", "recording-stopped"].includes(phase) ? "録音"
    : screen === "home" && ["processing", "draft-error"].includes(phase) ? "下書き" : screens[screen];
  content.setAttribute("aria-label", title);
  content.scrollTop = 0;
  document.title = title === "ホーム" ? "NurseNote" : `${title} | NurseNote`;
  updateNavigation(navigation, screen);
  syncNavigationLock();
  if (focus) content.focus({ preventScroll: true });
}

function syncNavigationLock() {
  const { phase, review } = getState();
  for (const button of navigation.querySelectorAll("button")) {
    button.disabled = ["mic-request", "recording", "processing"].includes(phase) || review?.saveStatus === "saving";
  }
}

function navigate() {
  if (["mic-request", "recording", "processing"].includes(getState().phase) || getState().review?.saveStatus === "saving") {
    window.history.replaceState(null, "", "#home");
    return;
  }
  patientSheet?.close();
  if (getState().phase === "idle") selectPatient(null);
  setScreen(screenFromHash());
  toast.hidden = true;
  historyController?.abort();
  historyController = null;
  if (getState().screen === "history") {
    openHistoryRoute();
    return;
  }
  clearHistory();
  renderScreen({ focus: true });
  if (getState().screen === "tasks" || (getState().screen === "home" && getState().phase === "idle")) refreshTasks();
}

function openHistoryRoute() {
  if (getState().authentication !== "ready") return;
  const recordId = recordIdFromHash();
  if (recordId !== null) refreshRecordDetail(recordId);
  else refreshRecordList();
}

async function refreshRecordList() {
  if (getState().authentication !== "ready" || getState().screen !== "history") return;
  historyController?.abort();
  const controller = new AbortController();
  historyController = controller;
  const version = sessionVersion;
  const patientId = getState().history.patientId;
  setHistoryState({ status: "loading", error: "", records: [], recordId: null,
    record: null, detailStatus: "idle", detailError: "" });
  renderScreen();
  try {
    const [records, patients] = await Promise.all([
      loadRecords({ patientId, signal: controller.signal }),
      loadPatients({ signal: controller.signal }),
    ]);
    if (controller.signal.aborted || version !== sessionVersion) return;
    setHistoryState({ records, patients, status: "ready", error: "" });
  } catch (error) {
    if (controller.signal.aborted || version !== sessionVersion || error.status === 401) return;
    setHistoryState({ records: [], status: "error", error: error.message });
  } finally {
    if (historyController === controller) historyController = null;
    if (!controller.signal.aborted && version === sessionVersion && getState().screen === "history"
      && getState().history.recordId === null) renderScreen();
  }
}

async function refreshRecordDetail(recordId) {
  if (getState().authentication !== "ready" || getState().screen !== "history") return;
  historyController?.abort();
  const controller = new AbortController();
  historyController = controller;
  const version = sessionVersion;
  // 不正な空IDも詳細のエラーとして表示し、一覧や別の記録を代わりに出しません。
  setHistoryState({ recordId: recordId || "invalid", record: null, detailStatus: "loading", detailError: "" });
  renderScreen({ focus: true });
  try {
    const record = await loadRecord(recordId, { signal: controller.signal });
    if (controller.signal.aborted || version !== sessionVersion) return;
    setHistoryState({ record, detailStatus: "ready", detailError: "" });
  } catch (error) {
    if (controller.signal.aborted || version !== sessionVersion || error.status === 401) return;
    const message = error.status === 404 ? "記録が見つかりません。保存期限を過ぎた可能性があります。" : error.message;
    setHistoryState({ record: null, detailStatus: "error", detailError: message });
  } finally {
    if (historyController === controller) historyController = null;
    if (!controller.signal.aborted && version === sessionVersion && getState().screen === "history") renderScreen();
  }
}

async function beginDraft(patient) {
  const state = getState();
  const isText = state.inputMethod === "text";
  if (state.authentication !== "ready" || (!isText && !state.consentConfirmed)
    || state.selectedPatient?.id !== patient.id || draftController || (!isText && !state.recorder?.result)) return;
  const version = sessionVersion;
  const recorder = getState().recorder;
  const controller = new AbortController();
  draftController = controller;
  setDraftPhase("processing");
  renderScreen({ focus: true });
  try {
    const options = { firstSpeaker: state.firstSpeaker, signal: controller.signal };
    const review = isText ? await createTextReview(patient, state.transcript, options)
      : await createAudioReview(patient, recorder.result, { ...options, consentConfirmed: true });
    if (controller.signal.aborted || version !== sessionVersion || (!isText && getState().recorder !== recorder)) {
      review.dispose();
      return;
    }
    setReview(review);
    renderScreen({ focus: true });
  } catch (error) {
    if (controller.signal.aborted || version !== sessionVersion || error.status === 401) return;
    setDraftPhase("draft-error", error.message);
    renderScreen({ focus: true });
  } finally {
    if (draftController === controller) draftController = null;
  }
}

async function beginRecording(patient) {
  const state = getState();
  if (state.authentication !== "ready" || !state.consentConfirmed || state.selectedPatient?.id !== patient.id
    || ["mic-request", "recording", "processing", "review", "export"].includes(state.phase)) return;
  const version = sessionVersion;
  const current = () => getState().recorder === recorder && !recorder.disposed
    && version === sessionVersion && getState().authentication === "ready";
  const recorder = new AudioRecorder({
    onTick() {
      const root = content.querySelector(".recording-screen");
      if (root && current()) refreshRecordingStatus(root, recorder, getState().phase);
    },
    onStopped(result) {
      if (!current()) return;
      if (result.reason === "interrupted" || document.hidden) {
        setDraftPhase("recording-stopped");
        renderScreen({ focus: true });
      } else {
        if (result.reason === "limit") showToast("録音時間の上限で停止しました");
        beginDraft(patient);
      }
    },
    onError(error) {
      if (!current()) return;
      setDraftPhase("recording-error", error.message, error.code);
      renderScreen({ focus: true });
    },
  });
  setScreen("home");
  window.history.replaceState(null, "", "#home");
  setRecorder(recorder);
  renderScreen({ focus: true });
  try {
    const started = await recorder.start({ consentConfirmed: state.consentConfirmed });
    if (!started || !current()) return;
    setDraftPhase("recording");
    renderScreen({ focus: true });
  } catch (error) {
    if (!current()) return;
    setDraftPhase("recording-error", error.message, error.code);
    renderScreen({ focus: true });
  }
}

function rerenderReview(session) {
  if (getState().review !== session || getState().screen !== "home") return;
  const active = document.activeElement;
  const focusKey = active?.dataset.focusKey;
  const start = active?.selectionStart;
  const end = active?.selectionEnd;
  const scroll = content.scrollTop;
  const opened = [...content.querySelectorAll("details[open][data-details-key]")]
    .map((details) => details.dataset.detailsKey);
  for (const audio of content.querySelectorAll("audio")) audio.pause();
  content.replaceChildren(renderReview(session));
  fitReviewTextareas();
  for (const details of content.querySelectorAll("[data-details-key]")) {
    if (opened.includes(details.dataset.detailsKey)) details.open = true;
  }
  const next = [...content.querySelectorAll("[data-focus-key]")].find((field) => field.dataset.focusKey === focusKey);
  if (next && !next.disabled) {
    next.focus({ preventScroll: true });
    if (typeof start === "number" && typeof next.setSelectionRange === "function") next.setSelectionRange(start, end);
  }
  content.scrollTop = scroll;
}

async function runVerification() {
  const session = getState().review;
  if (!session || session.disposed || session.isLocked() || session.status === "verifying") return;
  const pending = session.verify();
  const root = content.querySelector(".review-screen");
  if (root) refreshReviewStatus(root, session);
  try {
    await pending;
  } catch {
    // エラーはセッション内に保持し、401は共通認証処理に任せます。
  }
  if (getState().review === session && !session.disposed) rerenderReview(session);
}

async function confirmDraft() {
  const session = getState().review;
  if (!session || session.disposed || session.saveStatus === "saving"
    || (!session.canRetrySave() && !session.gate().ready)) return;
  for (const audio of content.querySelectorAll("audio")) audio.pause();
  try {
    const pending = session.confirm();
    const root = content.querySelector(".review-screen");
    if (root) refreshReviewStatus(root, session);
    syncNavigationLock();
    const result = await pending;
    if (!result || getState().review !== session || getState().authentication !== "ready") return;
    setConfirmedRecord(result);
    taskController?.abort();
    taskController = null;
    setScreen("home");
    window.history.replaceState(null, "", "#home");
    renderScreen({ focus: true });
    refreshExportRecord();
    refreshTasks();
  } catch (error) {
    if (getState().review !== session || session.disposed) return;
    if (!session.saveError) session.saveError = error.message;
    rerenderReview(session);
  } finally {
    syncNavigationLock();
  }
}

async function refreshExportRecord() {
  const record = getState().confirmedRecord;
  if (!record || exportController || getState().authentication !== "ready") return;
  const controller = new AbortController();
  exportController = controller;
  setExportState(record.record_id, { status: "loading", error: "" });
  const refresh = () => {
    const state = getState();
    if (state.confirmedRecord !== record || state.screen !== "home" || state.phase !== "export") return;
    const root = content.querySelector(".export-screen");
    if (root) refreshExportDetails(root, record);
  };
  refresh();
  try {
    const detail = await loadRecord(record.record_id, { signal: controller.signal });
    if (controller.signal.aborted || getState().confirmedRecord !== record) return;
    if (detail.chart_text !== record.chart_text) throw new Error("保存した記録と表示内容が一致しません。");
    setExportState(record.record_id, { record: detail, status: "ready", error: "" });
  } catch (error) {
    if (controller.signal.aborted || getState().confirmedRecord !== record || error.status === 401) return;
    setExportState(record.record_id, { status: "error", error: error.message });
  } finally {
    if (exportController === controller) exportController = null;
    if (!controller.signal.aborted) refresh();
  }
}

function cancelExportRequest() {
  exportController?.abort();
  exportController = null;
}

function returnHome() {
  cancelExportRequest();
  clearReview();
  selectPatient(null);
  setScreen("home");
  window.history.replaceState(null, "", "#home");
  renderScreen({ focus: true });
  refreshTasks();
}

async function copyRecord(button) {
  const record = button.dataset.historyAction === "copy" ? getState().history.record : getState().confirmedRecord;
  if (!record || button.disabled) return;
  button.disabled = true;
  const root = button.closest(".export-screen, .record-detail-screen");
  const status = root.querySelector("[data-copy-status]");
  try {
    await navigator.clipboard.writeText(record.chart_text);
    if (root.isConnected) status.textContent = "コピーしました";
  } catch {
    if (root.isConnected) {
      const output = root.querySelector(".record-output");
      const fallback = root.querySelector("[data-copy-fallback]");
      fallback.hidden = false;
      fallback.open = true;
      output.focus({ preventScroll: true });
      output.select();
      status.textContent = "文章を選択しました。手動でコピーしてください。";
    }
  } finally {
    button.disabled = false;
  }
}

function discardDraft() {
  const session = getState().review;
  if (session?.saveStatus === "saving") return;
  const message = session?.canRetrySave()
    ? "保存済みの可能性があります。ブラウザ内の下書きを破棄しますか？"
    : "下書きを破棄しますか？";
  if (getState().phase === "review" && !window.confirm(message)) return;
  cancelExportRequest();
  draftController?.abort();
  draftController = null;
  for (const audio of content.querySelectorAll("audio")) audio.pause();
  clearReview();
  selectPatient(null);
  renderScreen({ focus: true });
  refreshTasks();
}

function refreshHomeTasks(focusTaskId) {
  updateTaskCount(navigation, getState());
  const section = content.querySelector(".tasks-screen, .task-section");
  if (!section || getState().authentication !== "ready") return;
  const active = section.contains(document.activeElement) ? document.activeElement : null;
  const activeId = active?.id;
  const activeView = active?.dataset.taskView;
  const activeAction = active?.dataset.action;
  const activeTaskId = active?.dataset.taskId;
  const scroll = content.scrollTop;
  const expanded = [...section.querySelectorAll(".task-card")]
    .filter((card) => card.querySelector("details[open]"))
    .map((card) => card.dataset.taskId);
  if (section.matches(".tasks-screen")) renderTasksContent(section, getState());
  else renderHomeTasks(section, getState());
  let nextFocus;
  if (activeId) nextFocus = [...section.querySelectorAll("[id]")].find((node) => node.id === activeId);
  if (activeView) nextFocus = [...section.querySelectorAll("[data-task-view]")].find((node) => node.dataset.taskView === activeView);
  for (const card of section.querySelectorAll(".task-card")) {
    if (expanded.includes(card.dataset.taskId)) card.querySelector("details")?.setAttribute("open", "");
    if (card.dataset.taskId === activeTaskId) {
      nextFocus = [...card.querySelectorAll("[data-action]")].find((node) => node.dataset.action === activeAction);
    }
  }
  if (!nextFocus && focusTaskId) {
    const card = [...section.querySelectorAll(".task-card")].find((node) => node.dataset.taskId === focusTaskId);
    nextFocus = card?.querySelector('[data-action="edit-task"]')
      ?? section.querySelector('[data-action="complete-task"], [data-action="reopen-task"], #task-patient');
  }
  if (nextFocus && !nextFocus.disabled) nextFocus.focus({ preventScroll: true });
  content.scrollTop = scroll;
}

async function refreshTasks() {
  if (getState().authentication !== "ready" || taskController) return;
  if (getState().pendingTaskIds.length) {
    taskRefreshQueued = true;
    return;
  }
  taskRefreshQueued = false;
  const version = sessionVersion;
  const controller = new AbortController();
  taskController = controller;
  setTaskState({ status: "loading", error: "" });
  refreshHomeTasks();
  try {
    // 看護師の一覧と受け持ちは担当の表示だけに使うので、読めなくてもタスクは出します（S-08）
    const [tasks] = await Promise.all([loadTasks({ signal: controller.signal }),
      ensureNurses({ signal: controller.signal }).then(() => loadAssignees({ signal: controller.signal }))]);
    if (version !== sessionVersion || controller.signal.aborted) return;
    setTaskState({ tasks, status: "ready", error: "", errors: {},
      patientId: tasks.some((task) => task.patient_id === getState().taskPatientId) ? getState().taskPatientId : "" });
  } catch (error) {
    if (version !== sessionVersion || controller.signal.aborted || error.status === 401) return;
    setTaskState({ tasks: [], status: "error", error: error.message });
  } finally {
    if (taskController === controller) taskController = null;
    if (version === sessionVersion) refreshHomeTasks();
  }
}

async function updateTask(id, action, changes = {}) {
  const state = getState();
  if (state.authentication !== "ready" || state.taskStatus !== "ready" || state.pendingTaskIds.includes(id)) return false;
  const task = state.tasks.find((item) => item.id === id);
  if (!task || task.status !== (action === "reopen" ? "done" : "open")) return false;
  if (action === "edit" && !Object.keys(changes).length) return true;
  const version = sessionVersion;
  const controller = new AbortController();
  taskUpdates.set(id, controller);
  let reload = false;
  const errors = { ...state.taskErrors };
  delete errors[id];
  setTaskState({ pendingIds: [...state.pendingTaskIds, id], errors });
  refreshHomeTasks();
  try {
    const operation = action === "complete" ? completeTask : action === "reopen" ? reopenTask : changeTaskDetails;
    const updated = await operation(task, { ...changes, signal: controller.signal });
    if (version !== sessionVersion || controller.signal.aborted) return false;
    // 完了・区分・分類は、保存が成功するまでは表示を動かしません。
    setTaskState({ tasks: getState().tasks.map((item) => item.id === id ? updated : item) });
    if (action === "complete") showToast("完了にしました");
    if (action === "reopen") showToast("未完了に戻しました");
    if (action === "edit") showToast("タスクを変更しました");
    return true;
  } catch (error) {
    if (version !== sessionVersion || controller.signal.aborted || error.status === 401) return false;
    setTaskState({ errors: { ...getState().taskErrors, [id]: error.message } });
    showToast(error.message);
    reload = error.status === 404;
    return false;
  } finally {
    if (taskUpdates.get(id) === controller) taskUpdates.delete(id);
    if (version === sessionVersion) {
      setTaskState({ pendingIds: getState().pendingTaskIds.filter((pending) => pending !== id) });
      refreshHomeTasks(id);
      if (reload || getState().phase === "export") taskRefreshQueued = true;
      if (!getState().pendingTaskIds.length && taskRefreshQueued) refreshTasks();
    }
  }
}

async function changeAssignee(patientId, nurseId) {
  if (getState().authentication !== "ready" || !nurseId) return;
  const version = sessionVersion;
  // 呼んだ時点で「変更中」になる（最初の await の前に印を付ける）ので、先に描き直して表の欄を押せなくします
  const pending = changePatientAssignee(patientId, nurseId);
  refreshHomeTasks();
  let moved = 0;
  try {
    ({ moved } = await pending);
    if (version !== sessionVersion) return;
    showToast(`受け持ちを${nurseName(nurseId)}さんにしました${moved ? `（タスク${moved}件も移しました）` : ""}`);
  } catch (error) {
    if (version === sessionVersion && error.status !== 401) showToast(error.message);
  } finally {
    if (version === sessionVersion) {
      refreshHomeTasks();
      // タスクが移ったときだけ、担当を出し直すために一覧を読み直します
      if (moved) refreshTasks();
    }
  }
}

function cancelTaskRequests() {
  taskChoiceDialog?.close();
  taskController?.abort();
  taskController = null;
  for (const controller of taskUpdates.values()) controller.abort();
  taskUpdates.clear();
  taskRefreshQueued = false;
}

function openTaskChoiceDialog(taskId) {
  const state = getState();
  if (taskChoiceDialog || patientSheet || state.authentication !== "ready"
    || state.taskStatus !== "ready" || state.pendingTaskIds.includes(taskId)) return;
  const task = state.tasks.find((item) => item.id === taskId && item.status === "open");
  if (!task) return;
  const screen = state.screen;
  const version = sessionVersion;
  // 担当はサーバーに保存する本物の担当（S-08）。看護師の一覧が読めなければ担当の欄は出しません
  const assignment = task.assigned_to ?? "";
  const popup = createTaskChoiceDialog({
    host: document.getElementById("overlay-root"),
    task,
    assignment,
    assignees: taskAssigneeOptions(task),
    assignmentNote: taskAssigneeNote(task),
    loadCategories: loadTaskCategories,
    async onConfirm({ urgency, category, assignment: nextAssignment }) {
      const changes = {};
      if (urgency !== task.urgency) changes.urgency = urgency;
      if (category !== taskCategory(task)) changes.category = category;
      if (nextAssignment && nextAssignment !== assignment) changes.assignedTo = nextAssignment;
      const saved = await updateTask(taskId, "edit", changes);
      if (!saved || version !== sessionVersion) throw new Error(getState().taskErrors[taskId]
        || "タスクの状態が変わりました。閉じて一覧を確認してください。");
    },
    onClose({ restoreFocus }) {
      if (taskChoiceDialog !== popup) return;
      taskChoiceDialog = null;
      if (restoreFocus && getState().authentication === "ready" && getState().screen === screen) {
        [...content.querySelectorAll("button[data-task-id][data-action]")]
          .find((button) => button.dataset.taskId === taskId
            && button.dataset.action === "edit-task")?.focus({ preventScroll: true });
      }
    },
  });
  taskChoiceDialog = popup;
  popup.open();
}

function openPatientSheet(inputMethod = "audio") {
  if (patientSheet || getState().authentication !== "ready") return;
  selectPatient(null);
  const sheet = createPatientSheet({
    host: document.getElementById("overlay-root"),
    inputMethod,
    onSelect: selectPatient,
    onConsent(patient, { firstSpeaker }) {
      if (getState().authentication !== "ready" || getState().selectedPatient?.id !== patient.id) return false;
      setFirstSpeaker(firstSpeaker);
      if (inputMethod === "text") {
        openTextInput();
        queueMicrotask(() => renderScreen({ focus: true }));
        return true;
      }
      if (!confirmConsent()) return false;
      queueMicrotask(() => beginRecording(patient));
      return true;
    },
    onClose({ confirmed }) {
      if (patientSheet !== sheet) return;
      patientSheet = null;
      if (!confirmed) selectPatient(null);
    },
  });
  patientSheet = sheet;
  sheet.open();
}

function finishAuthentication({ focus = false } = {}) {
  cancelExportRequest();
  sessionVersion += 1;
  cancelTaskRequests();
  draftController?.abort();
  draftController = null;
  historyController?.abort();
  historyController = null;
  clearPatientData();
  setAuthentication("ready");
  renderScreen({ focus });
  refreshTasks();
  if (getState().screen === "history") openHistoryRoute();
}

function renderAuthentication({ message = "", pending = false, retry = false } = {}) {
  taskChoiceDialog?.close();
  updateTaskCount(navigation, getState());
  for (const audio of content.querySelectorAll("audio")) audio.pause();
  navigation.hidden = true;
  toast.hidden = true;
  content.setAttribute("aria-label", "合言葉");
  document.title = "合言葉 | NurseNote";
  content.replaceChildren(renderAuth({
    message,
    pending,
    onSubmit: signIn,
    onRetry: retry ? restoreAuthentication : undefined,
  }));
}

async function signIn(passcode) {
  // ログイン専用APIはないため、読み取り専用の患者一覧APIで確認します。
  await getPatients({ passcode });
  setPasscode(passcode);
  finishAuthentication({ focus: true });
}

async function restoreAuthentication() {
  const passcode = getPasscode();
  if (!passcode) {
    setAuthentication("required");
    renderAuthentication();
    return;
  }

  setAuthentication("checking");
  renderAuthentication({ pending: true });
  try {
    await getPatients({ passcode });
    if (getPasscode() !== passcode) return;
    finishAuthentication();
  } catch (error) {
    // 401は共通イベントで入力画面に戻します。通信失敗では合言葉を消しません。
    if (error.status !== 401) {
      setAuthentication("required");
      renderAuthentication({ message: error.message, retry: true });
    }
  }
}

function renderMode() {
  const { mode } = getState();
  modeBadge.textContent = mode === "mock" ? "デモ" : mode === "live" ? "本番" : "未接続";
  modeBadge.setAttribute("aria-label", mode ? `動作モード：${modeBadge.textContent}` : "API未接続");
  if (mode) modeBadge.dataset.mode = mode;
  else delete modeBadge.dataset.mode;
}

async function checkConnection() {
  try {
    const { mode } = await getHealth();
    setConnection(mode);
  } catch {
    // 通信失敗時にモックへ切り替えたり、本番と表示したりしません。
    // 同時に呼んだ別のAPIで取得できたmodeは維持します。
    if (getState().mode === null) setConnection(null);
  }
  renderMode();
}

navigation.addEventListener("click", (event) => {
  if (getState().authentication !== "ready") return;
  const button = event.target.closest("button[data-screen]");
  if (button?.dataset.screen === "home" && getState().phase === "export") {
    returnHome();
    return;
  }
  if (!button || (button.dataset.screen === getState().screen
    && !(button.dataset.screen === "history" && recordIdFromHash() !== null))) return;
  window.location.hash = button.dataset.screen;
});

content.addEventListener("click", (event) => {
  const taskScope = event.target.closest("[data-task-scope]");
  if (taskScope && !taskScope.disabled) {
    setTaskScope(taskScope.dataset.taskScope);
    refreshHomeTasks();
    return;
  }
  const taskView = event.target.closest("[data-task-view]");
  if (taskView && !taskView.disabled) {
    setTaskState({ view: taskView.dataset.taskView });
    refreshHomeTasks();
    return;
  }
  const historyAction = event.target.closest("[data-history-action]");
  if (historyAction && !historyAction.disabled) {
    if (historyAction.dataset.historyAction === "refresh") refreshRecordList();
    if (historyAction.dataset.historyAction === "retry-detail") refreshRecordDetail(recordIdFromHash() ?? "");
    if (historyAction.dataset.historyAction === "copy") copyRecord(historyAction);
    return;
  }
  const exportAction = event.target.closest("[data-export-action]");
  if (exportAction && !exportAction.disabled) {
    if (exportAction.dataset.exportAction === "copy") copyRecord(exportAction);
    if (exportAction.dataset.exportAction === "home") returnHome();
    if (exportAction.dataset.exportAction === "retry-details") refreshExportRecord();
    return;
  }
  const reviewAction = event.target.closest("[data-review-action]");
  if (reviewAction && !reviewAction.disabled) {
    const session = getState().review;
    const action = reviewAction.dataset.reviewAction;
    if (action === "discard") discardDraft();
    if (action === "retry-draft" && getState().selectedPatient) beginDraft(getState().selectedPatient);
    if (action === "submit-text" && getState().selectedPatient) beginDraft(getState().selectedPatient);
    if (action === "edit-text") { openTextInput(); renderScreen({ focus: true }); }
    if (action === "restart-recording" && getState().selectedPatient) beginRecording(getState().selectedPatient);
    if (action === "stop-recording") getState().recorder?.stop();
    if (action === "verify") runVerification();
    if (action === "confirm") confirmDraft();
    if (action === "swap-speakers" && session?.swapSpeakers()) rerenderReview(session);
    if (action === "show-check" && session) {
      const target = [...content.querySelectorAll("[data-alert-path]")]
        .find((card) => card.dataset.alertPath === reviewAction.dataset.path);
      if (target) {
        target.focus({ preventScroll: true });
        target.scrollIntoView({ block: "start" });
      }
    }
    if (action === "add-entry" && session) {
      const path = session.addElement(reviewAction.dataset.kind);
      if (path) {
        rerenderReview(session);
        const input = [...content.querySelectorAll("textarea[data-path]")].find((field) => field.dataset.path === path);
        input?.focus();
      }
    }
    if (action === "remove-entry" && session && session.removeAdded(reviewAction.dataset.path)) {
      rerenderReview(session);
      const kind = reviewAction.dataset.path.split("[")[0];
      [...content.querySelectorAll('[data-review-action="add-entry"]')].find((button) => button.dataset.kind === kind)?.focus({ preventScroll: true });
      runVerification();
    }
    if (action === "decide" && session) {
      session.decide(reviewAction.dataset.path, reviewAction.dataset.decision);
      rerenderReview(session);
    }
    if (action === "confirm-multiple" && session) {
      session.confirmMultiple(reviewAction.dataset.path);
      refreshReviewStatus(content.querySelector(".review-screen"), session);
    }
    return;
  }
  if (event.target.closest(".task-evidence")) return;
  const action = event.target.closest("[data-action]");
  if (!action || action.disabled) return;
  if (action.dataset.action === "choose-patient") openPatientSheet();
  if (action.dataset.action === "choose-text-patient") openPatientSheet("text");
  if (action.dataset.action === "refresh-tasks") refreshTasks();
  if (action.dataset.action === "edit-task") openTaskChoiceDialog(action.dataset.taskId);
  if (action.dataset.action === "toggle-assignees") { toggleAssigneeTable(); refreshHomeTasks(); }
  if (action.dataset.action === "complete-task") updateTask(action.dataset.taskId, "complete");
  if (action.dataset.action === "reopen-task") updateTask(action.dataset.taskId, "reopen");
});

content.addEventListener("input", (event) => {
  const input = event.target;
  if (input.id === "transcript-input") {
    setTranscript(input.value);
    refreshTextInput(content.querySelector(".text-input-screen"), input.value);
    return;
  }
  const session = getState().review;
  if (!session || session.disposed) return;
  if (input.dataset.reviewField === "vital") {
    const index = input.dataset.vitalIndex === "" ? null : Number(input.dataset.vitalIndex);
    const position = session.setVital(index, input.dataset.vitalItem, input.value);
    if (position !== null) input.dataset.vitalIndex = String(position);
  } else if (input.dataset.reviewField === "soap") {
    session.setSoap(input.dataset.part, Number(input.dataset.sentenceIndex ?? 0), input.value);
    fitTextarea(input);
  } else if (input.dataset.reviewField === "element") {
    session.setElement(input.dataset.path, input.value);
    fitTextarea(input);
  } else return;
  refreshReviewStatus(content.querySelector(".review-screen"), session);
});

content.addEventListener("change", (event) => {
  const input = event.target;
  if (input.id === "task-patient") {
    setTaskState({ patientId: input.value });
    refreshHomeTasks();
    return;
  }
  if (input.dataset.patientAssignee) {
    changeAssignee(input.dataset.patientAssignee, input.value);
    return;
  }
  if (input.id === "task-my-nurse") {
    setMyNurseId(input.value);
    refreshHomeTasks();
    return;
  }
  if (input.id === "history-patient") {
    setHistoryState({ patientId: input.value });
    refreshRecordList();
    return;
  }
  const session = getState().review;
  if (!session || session.disposed) return;
  if (input.dataset.reviewField === "patient-confirmed") {
    session.confirmPatient(input.checked);
    input.checked = session.patientConfirmed;
    refreshReviewStatus(content.querySelector(".review-screen"), session);
  } else if (input.dataset.reviewField === "evidence") {
    session.setEvidence(input.dataset.path, input.dataset.utteranceId, input.checked);
    rerenderReview(session);
    runVerification();
  } else if (input.dataset.reviewField === "request-urgency") {
    session.setRequestUrgency(Number(input.dataset.requestIndex), input.value);
    refreshReviewStatus(content.querySelector(".review-screen"), session);
    runVerification();
  } else if (["vital", "soap", "element"].includes(input.dataset.reviewField)
    && session.revision !== session.verifiedRevision) runVerification();
});

window.addEventListener("hashchange", navigate);
window.addEventListener("online", checkConnection);
window.addEventListener("resize", fitReviewTextareas);
window.addEventListener(MODE_EVENT, (event) => {
  setConnection(event.detail.mode);
  renderMode();
});
window.addEventListener(AUTH_REQUIRED_EVENT, (event) => {
  cancelExportRequest();
  sessionVersion += 1;
  cancelTaskRequests();
  draftController?.abort();
  draftController = null;
  historyController?.abort();
  historyController = null;
  patientSheet?.close();
  clearPatientData();
  setAuthentication("required");
  renderAuthentication({ message: event.detail.message });
  content.focus({ preventScroll: true });
});
document.addEventListener("visibilitychange", () => {
  const recorder = getState().recorder;
  if (document.hidden && recorder?.status === "recording") recorder.stop("interrupted");
  if (document.hidden && recorder?.status === "requesting") {
    recorder.dispose();
    setDraftPhase("recording-error", "録音を中止しました。もう一度お試しください。");
    renderScreen();
  }
  if (!document.hidden && getState().screen === "home" && getState().phase === "idle" && !patientSheet) refreshTasks();
  if (!document.hidden && getState().screen === "tasks") refreshTasks();
  if (!document.hidden && getState().screen === "history" && !historyController) openHistoryRoute();
});

window.addEventListener("pagehide", () => {
  cancelExportRequest();
  draftController?.abort();
  draftController = null;
  for (const audio of content.querySelectorAll("audio")) audio.pause();
  clearReview();
  selectPatient(null);
  renderScreen();
});

setScreen(screenFromHash());
renderNavigation(navigation, getState().screen);
restoreAuthentication();
checkConnection();
