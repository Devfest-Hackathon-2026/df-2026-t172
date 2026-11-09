import { element, reviewButton } from "../components/review-dom.js";
import { displayName } from "../patients.js";
import { transcriptError } from "../records.js";

export function renderTextInput(patient, transcript) {
  const view = element("section", "text-input-screen");
  view.append(element("h1", "page-title", "テキスト入力"));
  view.append(element("p", "patient-room", `${patient.room}号室　ベッド${patient.bed}`),
    element("h2", "review-patient-name", displayName(patient)));
  const label = element("label", "form-label", "会話");
  label.htmlFor = "transcript-input";
  const input = element("textarea", "textarea transcript-input");
  input.id = "transcript-input";
  input.value = transcript;
  input.rows = 9;
  input.placeholder = "看護師: 体温は36.8度ですね。\n患者: 昨夜はあまり眠れませんでした。";
  input.setAttribute("aria-describedby", "transcript-guide transcript-count transcript-error");
  const guide = element("p", "empty-inline", "1行1発言。「看護師:」「患者:」で始めてください。");
  guide.id = "transcript-guide";
  const count = element("p", "copy-status");
  count.id = "transcript-count";
  const error = element("p", "form-error");
  error.id = "transcript-error";
  error.setAttribute("role", "alert");
  view.append(label, input, guide, count, error, reviewButton("下書きを作成", "submit-text", "primary-button"), reviewButton("破棄", "discard"));
  refreshTextInput(view, transcript);
  return view;
}

export function refreshTextInput(root, transcript) {
  const error = transcriptError(transcript);
  root.querySelector("#transcript-count").textContent = `${[...transcript].length} / 5,000文字`;
  root.querySelector("#transcript-error").textContent = transcript.trim() ? error : "";
  root.querySelector("#transcript-input").setAttribute("aria-invalid", String(Boolean(error && transcript.trim())));
  root.querySelector('[data-review-action="submit-text"]').disabled = Boolean(error);
}
