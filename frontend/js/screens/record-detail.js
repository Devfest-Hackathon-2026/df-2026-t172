import { element } from "../components/review-dom.js";
import { renderCopyFallback, renderRecordSummary } from "../components/record-summary.js?v=20261121-context-help";
import { historyButton, renderHistoryStatus } from "./history.js?v=20261121-context-help";

export function renderRecordDetail(history) {
  const view = element("section", "record-detail-screen");
  if (history.detailStatus !== "ready" || !history.record) {
    view.append(renderHistoryStatus(history.detailStatus, history.detailError, "記録はありません", "retry-detail"));
    return view;
  }
  const record = history.record;
  const actions = element("div", "saved-record-actions");
  actions.append(historyButton("編集", "edit"), historyButton("コピー", "copy", "primary-button"));
  view.append(renderRecordSummary(record, { showEvidence: true, patientHeading: "h1" }), actions);
  const status = element("p", "copy-status");
  status.setAttribute("role", "status");
  status.dataset.copyStatus = "";
  view.append(status, renderCopyFallback(record.chart_text));
  return view;
}
