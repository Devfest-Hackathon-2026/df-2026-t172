import { element } from "../components/review-dom.js";
import { renderCopyFallback, renderRecordSummary } from "../components/record-summary.js?v=20261121-context-help";

export function refreshExportDetails(root, record) {
  const container = root.querySelector("[data-export-details]");
  container.replaceChildren();
  container.setAttribute("aria-busy", String(record.detailStatus === "loading"));
  if (record.details) {
    container.append(renderRecordSummary(record.details));
  } else if (record.detailStatus === "error") {
    const error = element("p", "form-error", `記録は保存済みです。${record.detailError}`);
    error.setAttribute("role", "alert");
    const retry = element("button", "secondary-button", "表示を再読み込み");
    retry.type = "button";
    retry.dataset.exportAction = "retry-details";
    container.append(error, retry);
  } else {
    const loading = element("p", "record-loading", "記録を読み込み中…");
    loading.setAttribute("role", "status");
    container.append(loading);
  }
}

export function renderExport(record) {
  const view = element("section", "export-screen");
  view.append(element("h1", "page-title", "記録を確定しました"));
  const container = element("div");
  container.dataset.exportDetails = "";
  view.append(container);
  refreshExportDetails(view, record);
  const copy = element("button", "primary-button", "コピー");
  copy.type = "button";
  copy.dataset.exportAction = "copy";
  const status = element("p", "copy-status");
  status.setAttribute("role", "status");
  status.dataset.copyStatus = "";
  const home = element("button", "secondary-button", "ホームへ");
  home.type = "button";
  home.dataset.exportAction = "home";
  view.append(copy, status,
    element("p", "export-edit-help", "保存した記録は「会話記録」から開き、「編集」で直せます。"),
    home, renderCopyFallback(record.chart_text));
  return view;
}
