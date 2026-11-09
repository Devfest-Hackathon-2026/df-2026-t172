import { element } from "../components/review-dom.js";
import { renderCopyFallback, renderRecordSummary } from "../components/record-summary.js";
import { historyButton, renderHistoryStatus } from "./history.js";

export function renderRecordDetail(history) {
  const view = element("section", "record-detail-screen");
  const back = element("a", "history-back", "一覧へ");
  back.href = "#history";
  view.append(back, element("h1", "page-title", "記録の詳細"));
  if (history.detailStatus !== "ready" || !history.record) {
    view.append(renderHistoryStatus(history.detailStatus, history.detailError, "記録はありません", "retry-detail"));
    return view;
  }
  const record = history.record;
  view.append(renderRecordSummary(record, { showEvidence: true }), historyButton("コピー", "copy", "primary-button"));
  const status = element("p", "copy-status");
  status.setAttribute("role", "status");
  status.dataset.copyStatus = "";
  view.append(status, renderCopyFallback(record.chart_text));
  return view;
}
