import { displayName } from "../patients.js";
import { element, reviewButton } from "../components/review-dom.js";

export function renderProcessing(patient, error, inputMethod = "audio") {
  const view = element("section", "processing-screen");
  view.append(element("p", "patient-room", `${patient.room}号室　ベッド${patient.bed}`));
  view.append(element("h1", "review-patient-name", displayName(patient)));
  if (error) {
    const message = element("p", "form-error", error);
    message.setAttribute("role", "alert");
    view.append(message, reviewButton("再送", "retry-draft", "primary-button"), inputMethod === "text"
      ? reviewButton("入力に戻る", "edit-text") : reviewButton("録り直す", "restart-recording"));
  } else {
    const spinner = element("span", "spinner");
    spinner.setAttribute("aria-hidden", "true");
    const status = element("p", "processing-label", "下書きを取得中…");
    status.setAttribute("role", "status");
    view.append(spinner, status);
  }
  view.append(reviewButton("中止", "discard"));
  return view;
}
