import { displayName } from "../patients.js";
import { element, reviewButton } from "../components/review-dom.js";
import { createIcon } from "../components/icons.js";

export function elapsedTime(seconds) {
  const value = Math.min(180, Math.max(0, Math.floor(seconds)));
  return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
}

export function renderRecording(patient, recorder, phase, error, errorCode = "") {
  const view = element("section", "recording-screen");
  view.append(element("p", "patient-room", `${patient.room}号室　ベッド${patient.bed}`));
  view.append(element("h1", "review-patient-name", displayName(patient)));
  const status = element("p", "recording-status");
  status.dataset.recordingStatus = "";
  status.setAttribute("role", "status");
  const time = element("p", "recording-time", elapsedTime(recorder?.duration() ?? 0));
  time.dataset.recordingTime = "";
  time.setAttribute("aria-label", "録音時間");
  time.hidden = Boolean(error);
  view.append(status, time);
  if (error) {
    const message = element("p", "form-error", error);
    message.setAttribute("role", "alert");
    const canRetry = !["recording_unavailable", "NotSupportedError", "insecure_context"].includes(errorCode);
    view.append(message, element("p", "empty-inline", "録音の代わりに、会話をテキストで入力できます。"));
    if (canRetry) view.append(reviewButton("再試行", "restart-recording", "primary-button"));
    view.append(reviewButton("テキスト入力へ", "edit-text", canRetry ? "secondary-button" : "primary-button"));
  } else if (phase === "recording-stopped") {
    view.append(reviewButton("下書きを作成", "retry-draft", "primary-button"), reviewButton("録り直す", "restart-recording"));
  } else {
    const stop = reviewButton("", "stop-recording", "recording-stop");
    stop.setAttribute("aria-label", "録音を停止");
    stop.append(createIcon("stop"));
    view.append(stop);
  }
  view.append(reviewButton("破棄", "discard", "text-button danger-text"));
  refreshRecordingStatus(view, recorder, phase);
  return view;
}

export function refreshRecordingStatus(root, recorder, phase) {
  root.querySelector("[data-recording-time]").textContent = elapsedTime(recorder?.duration() ?? 0);
  const status = root.querySelector("[data-recording-status]");
  status.textContent = phase === "recording-error" ? "録音できませんでした"
    : phase === "recording-stopped" ? "録音を停止しました"
    : recorder?.status === "stopping" ? "録音を停止中…"
    : recorder?.status === "recording" ? "録音中" : "マイクを確認中…";
  status.dataset.active = String(recorder?.status === "recording");
  const stop = root.querySelector('[data-review-action="stop-recording"]');
  if (stop) stop.disabled = recorder?.status !== "recording";
}
