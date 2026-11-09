import { createIcon } from "../components/icons.js";
import { renderTaskCard } from "../components/task-card.js?v=20261110-assign";
import { renderTaskScope } from "../components/task-assign.js?v=20261110-assign";
import { getTaskScope, scopedTasks } from "../assignment.js";
import { groupOpenTasks } from "../tasks.js?v=20261110-assign";

export function renderHome(state) {
  const view = document.createElement("div");

  const title = document.createElement("h1");
  title.className = "screen-reader-only";
  title.textContent = "ホーム";

  const micArea = document.createElement("div");
  micArea.className = "mic-area";
  const micButton = document.createElement("button");
  micButton.type = "button";
  micButton.className = "mic-button";
  micButton.dataset.action = "choose-patient";
  micButton.setAttribute("aria-label", "患者を選んで録音");
  micButton.append(createIcon("mic"));
  micArea.append(micButton);
  const textInput = document.createElement("button");
  textInput.type = "button";
  textInput.className = "text-button text-entry";
  textInput.dataset.action = "choose-text-patient";
  textInput.textContent = "テキストで入力";
  micArea.append(textInput);

  const tasks = document.createElement("section");
  tasks.className = "task-section";
  tasks.setAttribute("aria-labelledby", "home-tasks-title");
  const tasksTitle = document.createElement("h2");
  tasksTitle.className = "section-title";
  tasksTitle.id = "home-tasks-title";
  tasksTitle.textContent = "タスク";
  const heading = document.createElement("div");
  heading.className = "section-heading";
  const refresh = document.createElement("button");
  refresh.type = "button";
  refresh.className = "icon-button";
  refresh.dataset.action = "refresh-tasks";
  refresh.setAttribute("aria-label", "タスクを更新");
  refresh.append(createIcon("refresh"));
  heading.append(tasksTitle, refresh);
  const scope = document.createElement("div");
  scope.id = "home-task-scope";
  const list = document.createElement("div");
  list.id = "home-tasks";
  list.className = "task-groups";
  const note = document.createElement("p");
  note.className = "ai-note";
  note.textContent = "区分（急ぎ・時間指定）は、会話の中の言葉から機械的に分けたもので、AI の判断ではありません。押すと変えられます。";
  tasks.append(heading, note, scope, list);
  renderHomeTasks(tasks, state);

  view.append(title, micArea, tasks);
  return view;
}

export function renderHomeTasks(section, { tasks, taskStatus, taskError, pendingTaskIds, taskErrors = {} }) {
  // 「自分の担当だけ」はタスクの画面と同じ設定を使います（S-08）
  tasks = scopedTasks(tasks).filter((task) => task.status === "open");
  const scope = renderTaskScope();
  section.querySelector("#home-task-scope").replaceChildren(...(scope ? [scope] : []));
  const list = section.querySelector("#home-tasks");
  const refresh = section.querySelector('[data-action="refresh-tasks"]');
  const loading = taskStatus === "idle" || taskStatus === "loading";
  refresh.disabled = loading || pendingTaskIds.length > 0;
  list.setAttribute("aria-busy", String(loading));
  list.replaceChildren();

  if (loading || taskStatus === "error" || !tasks.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    const text = document.createElement("p");
    if (taskStatus === "error") {
      text.className = "form-error";
      text.setAttribute("role", "alert");
      text.textContent = taskError;
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "secondary-button";
      retry.dataset.action = "refresh-tasks";
      retry.textContent = "再試行";
      empty.append(text, retry);
    } else {
      text.setAttribute("role", "status");
      const owner = getTaskScope() === "mine" ? "自分の担当の" : "";
      text.textContent = loading ? "読み込み中…" : `${owner}未完了のタスクはありません`;
      empty.append(createIcon("tasks"), text);
    }
    list.append(empty);
    return;
  }

  for (const group of groupOpenTasks(tasks)) {
    const groupSection = document.createElement("section");
    groupSection.className = "task-group";
    groupSection.dataset.urgency = group.value;
    groupSection.setAttribute("aria-label", group.label);
    for (const task of group.tasks) {
      groupSection.append(renderTaskCard(task, { pending: pendingTaskIds.includes(task.id), error: taskErrors[task.id] }));
    }
    list.append(groupSection);
  }
}
