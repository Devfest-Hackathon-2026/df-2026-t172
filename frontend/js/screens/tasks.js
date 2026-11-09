import { displayName } from "../patients.js";
import { element } from "../components/review-dom.js";
import { createIcon } from "../components/icons.js";
import { renderTaskCard } from "../components/task-card.js?v=20261110-assign";
import { renderAssigneeTable, renderTaskScope } from "../components/task-assign.js?v=20261110-assign";
import { getTaskScope, scopedTasks } from "../assignment.js";
import { groupOpenTasks, taskPatients, visibleTasks } from "../tasks.js?v=20261110-assign";

export function renderTasks(state) {
  const view = element("section", "tasks-screen");
  const heading = element("div", "section-heading tasks-heading");
  heading.append(element("h1", "page-title", "タスク"));
  const refresh = element("button", "icon-button");
  refresh.type = "button";
  refresh.dataset.action = "refresh-tasks";
  refresh.setAttribute("aria-label", "タスクを更新");
  refresh.append(createIcon("refresh"));
  heading.append(refresh);
  view.append(heading);
  renderTasksContent(view, state);
  return view;
}

export function renderTasksContent(root, state) {
  const { taskStatus, taskError, pendingTaskIds, taskView, taskErrors } = state;
  // 「自分の担当だけ」なら、件数・患者の絞り込み・一覧のすべてをその範囲で数えます（S-08）
  const tasks = scopedTasks(state.tasks);
  // 範囲を狭めて選んでいた患者がいなくなったら、患者の絞り込みは外して見せます
  const taskPatientId = tasks.some((task) => task.patient_id === state.taskPatientId) ? state.taskPatientId : "";
  const mine = getTaskScope() === "mine";
  const loading = ["idle", "loading"].includes(taskStatus);
  root.querySelector('[data-action="refresh-tasks"]').disabled = loading || pendingTaskIds.length > 0;
  root.querySelector(".tasks-content")?.remove();
  const body = element("div", "tasks-content");
  const scope = renderTaskScope();
  if (scope) body.append(scope);
  const tabs = element("div", "task-view-switch");
  tabs.setAttribute("role", "group");
  tabs.setAttribute("aria-label", "タスクの状態");
  for (const [value, label] of [["open", "未完了"], ["done", "完了"]]) {
    const count = taskStatus === "ready" ? visibleTasks(tasks, { view: value, patientId: taskPatientId }).length : null;
    const button = element("button", "task-view-button", count === null ? label : `${label} ${count}`);
    button.type = "button";
    button.dataset.taskView = value;
    button.setAttribute("aria-pressed", String(taskView === value));
    tabs.append(button);
  }
  body.append(tabs);
  const label = element("label", "screen-reader-only", "患者で絞り込み");
  label.htmlFor = "task-patient";
  const filter = element("select", "input task-filter");
  filter.id = "task-patient";
  const all = element("option", "", "すべての患者");
  all.value = "";
  filter.append(all);
  for (const patient of taskPatients(tasks)) {
    const option = element("option", "", `${patient.room}号室　${displayName(patient)}`);
    option.value = patient.id;
    filter.append(option);
  }
  filter.value = taskPatientId;
  filter.disabled = loading || taskStatus !== "ready" || !tasks.length;
  body.append(label, filter);
  const list = element("div", "tasks-list task-groups");
  list.setAttribute("aria-busy", String(loading));
  const visible = visibleTasks(tasks, { patientId: taskPatientId, view: taskView });
  if (loading || taskStatus === "error" || !visible.length) {
    const box = element("div", "empty-state");
    const text = element("p", taskStatus === "error" ? "form-error" : "",
      taskStatus === "error" ? taskError : loading ? "読み込み中…"
        : `${mine ? "自分の担当の" : ""}${taskView === "done" ? "完了した" : "未完了の"}タスクはありません`);
    text.setAttribute("role", taskStatus === "error" ? "alert" : "status");
    box.append(text);
    if (taskStatus === "error") {
      const retry = element("button", "secondary-button", "再試行");
      retry.type = "button";
      retry.dataset.action = "refresh-tasks";
      box.append(retry);
    }
    list.append(box);
  } else {
    const appendCard = (parent, task) => parent.append(renderTaskCard(task, {
      pending: pendingTaskIds.includes(task.id), error: taskErrors[task.id],
    }));
    if (taskView === "done") {
      for (const task of visible) appendCard(list, task);
    } else {
      for (const group of groupOpenTasks(visible)) {
        const section = element("section", "task-group");
        section.dataset.urgency = group.value;
        section.setAttribute("aria-label", group.label);
        for (const task of group.tasks) appendCard(section, task);
        list.append(section);
      }
    }
  }
  body.append(list);
  const assignees = renderAssigneeTable();
  if (assignees) body.append(assignees);
  root.append(body);
}
