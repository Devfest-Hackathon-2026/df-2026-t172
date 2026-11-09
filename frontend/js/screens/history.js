import { displayName } from "../patients.js";
import { element } from "../components/review-dom.js";
import { createIcon } from "../components/icons.js";
import { recordTime } from "../history.js";

export function historyButton(label, action, className = "secondary-button") {
  const button = element("button", className, label);
  button.type = "button";
  button.dataset.historyAction = action;
  return button;
}

export function renderHistoryStatus(status, error, emptyMessage, retryAction) {
  const box = element("div", "empty-state");
  const message = element("p", error ? "form-error" : "", error || (status === "loading" || status === "idle" ? "読み込み中…" : emptyMessage));
  message.setAttribute("role", error ? "alert" : "status");
  box.append(message);
  if (error) box.append(historyButton("再試行", retryAction));
  return box;
}

export function renderHistory(history) {
  const view = element("section", "history-screen");
  const heading = element("div", "section-heading history-heading");
  const title = element("div", "history-title");
  const icon = element("span", "history-title-icon");
  icon.setAttribute("aria-hidden", "true");
  icon.append(createIcon("history"));
  title.append(icon, element("h1", "page-title", "会話記録"));
  heading.append(title);
  const refresh = historyButton("", "refresh", "icon-button");
  refresh.setAttribute("aria-label", "記録を更新");
  refresh.append(createIcon("refresh"));
  refresh.disabled = ["idle", "loading"].includes(history.status);
  heading.append(refresh);
  view.append(heading);
  const label = element("label", "screen-reader-only", "患者で絞り込み");
  label.htmlFor = "history-patient";
  const filter = element("select", "input history-filter");
  filter.id = "history-patient";
  const all = element("option", "", "すべての患者");
  all.value = "";
  filter.append(all);
  for (const patient of history.patients) {
    const option = element("option", "", `${patient.room}号室　ベッド${patient.bed}　${displayName(patient)}`);
    option.value = patient.id;
    filter.append(option);
  }
  filter.value = history.patientId;
  filter.disabled = ["idle", "loading"].includes(history.status) || !history.patients.length;
  view.append(label, filter);

  const list = element("div", "history-list");
  list.setAttribute("aria-busy", String(["idle", "loading"].includes(history.status)));
  if (history.status !== "ready" || !history.records.length) {
    list.append(renderHistoryStatus(history.status, history.error, "当日の記録はありません", "refresh"));
  } else {
    for (const record of history.records) {
      const link = element("a", "record-card");
      link.href = `#history/${record.record_id}`;
      const meta = element("div", "record-card-meta");
      const patient = element("div", "record-card-patient");
      patient.append(element("h2", "record-card-name", displayName(record)),
        element("span", "record-card-room", `${record.room}号室`));
      const time = element("time", "", recordTime(record.created_at));
      time.dateTime = record.created_at;
      const arrow = element("span", "record-card-arrow", "›");
      arrow.setAttribute("aria-hidden", "true");
      meta.append(patient, time, arrow);
      const preview = [record.s_preview, record.o_preview].find((text) => text?.trim());
      link.append(meta, element("p", "record-preview", preview ? preview.replace(/\s+/gu, " ").trim() : "記録の詳細"));
      list.append(link);
    }
  }
  view.append(list);
  return view;
}
