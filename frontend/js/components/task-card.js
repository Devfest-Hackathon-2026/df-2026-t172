import { displayName } from "../patients.js";
import { taskCategory, taskGroups } from "../tasks.js?v=20261110-assign";
import { renderTaskAssignee } from "./task-assign.js?v=20261110-assign";
import { createIcon } from "./icons.js?v=20261109-navy";

export function renderTaskCard(task, { pending = false, error = "" } = {}) {
  const card = document.createElement("article");
  card.className = "task-card";
  card.dataset.taskId = task.id;
  card.dataset.urgency = task.urgency;
  card.dataset.status = task.status;
  card.setAttribute("aria-busy", String(pending));
  if (task.status === "open") card.dataset.action = "edit-task";

  const main = document.createElement("div");
  main.className = "task-main";
  const body = document.createElement(task.status === "open" ? "button" : "div");
  body.className = "task-main-button";
  const urgencyLabel = taskGroups.find((group) => group.value === task.urgency).label;
  if (task.status === "open") {
    body.type = "button";
    body.dataset.action = "edit-task";
    body.dataset.taskId = task.id;
    body.disabled = pending;
    body.setAttribute("aria-haspopup", "dialog");
    body.setAttribute("aria-label", `${task.room}号室 ${displayName(task)}の依頼「${task.text}」。区分：${urgencyLabel}、分類：${taskCategory(task)}。タスクを変更`);
  }
  const meta = document.createElement("span");
  meta.className = "task-meta";
  const room = document.createElement("span");
  room.className = "task-room";
  room.textContent = `${task.room}号室`;
  const name = document.createElement("span");
  name.className = "task-patient";
  name.textContent = displayName(task);
  name.title = displayName(task);
  const urgency = document.createElement("span");
  urgency.className = "task-urgency-label";
  urgency.append(createIcon({ said_urgent: "alert", timed: "clock", none: "circle" }[task.urgency]),
    document.createTextNode({ said_urgent: "急ぎ", timed: "時間指定", none: "その他" }[task.urgency]));
  urgency.title = urgencyLabel;
  const category = document.createElement("span");
  category.className = "task-category-tag";
  category.textContent = taskCategory(task);
  meta.append(room, name, urgency, category);
  const summary = document.createElement("span");
  summary.className = "task-text";
  summary.textContent = task.text;
  body.append(summary);
  const assignee = renderTaskAssignee(task);
  if (assignee) body.append(assignee);
  main.append(meta, body);

  const complete = document.createElement("button");
  complete.className = task.status === "open" ? "task-complete" : "task-complete task-reopen";
  complete.append(createIcon(task.status === "open" ? "check" : "close"));
  complete.type = "button";
  complete.dataset.action = task.status === "open" ? "complete-task" : "reopen-task";
  complete.dataset.taskId = task.id;
  complete.disabled = pending;
  const action = task.status === "open" ? "完了" : "未完了に戻す";
  complete.setAttribute("aria-label", `${displayName(task)}の依頼「${task.text}」を${action}`);
  complete.title = action;
  card.append(main, complete);

  const evidence = document.createElement("details");
  evidence.className = "task-evidence";
  const toggle = document.createElement("summary");
  toggle.textContent = "発言内容を確認する";
  evidence.append(toggle);
  const words = (task.patient_words ?? []).filter((text) => text.trim());
  for (const text of words) {
    const quote = document.createElement("blockquote");
    quote.textContent = `「${text}」`;
    evidence.append(quote);
  }
  if (!words.length) {
    const empty = document.createElement("p");
    empty.textContent = "発言内容はありません";
    evidence.append(empty);
  }
  card.append(evidence);
  if (error) {
    const message = document.createElement("p");
    message.className = "form-error";
    message.setAttribute("role", "alert");
    message.textContent = error;
    card.append(message);
  }
  return card;
}
