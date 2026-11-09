import { getState, screens } from "../state.js";
import { createIcon } from "./icons.js";

export function renderNavigation(container, activeScreen) {
  const buttons = Object.entries(screens).map(([id, label]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "nav-button";
    button.dataset.screen = id;
    if (id === activeScreen) button.setAttribute("aria-current", "page");

    const text = document.createElement("span");
    text.textContent = label;
    const icon = document.createElement("span");
    icon.className = "nav-icon-wrap";
    icon.append(createIcon(id));
    if (id === "tasks") {
      const count = document.createElement("span");
      count.className = "nav-task-count";
      count.dataset.taskCount = "";
      count.setAttribute("aria-hidden", "true");
      count.hidden = true;
      icon.append(count);
    }
    button.append(icon, text);
    return button;
  });
  container.replaceChildren(...buttons);
  updateTaskCount(container, getState());
}

export function updateTaskCount(container, { tasks, taskStatus, authentication }) {
  const button = container.querySelector('[data-screen="tasks"]');
  const label = button?.querySelector("[data-task-count]");
  if (!label) return;
  const ready = authentication === "ready" && taskStatus === "ready";
  const count = ready ? tasks.filter((task) => task.status === "open").length : null;
  label.hidden = !ready;
  const value = ready ? String(count) : "";
  if (label.textContent !== value) label.textContent = value;
  button.setAttribute("aria-label", ready ? `タスク、未完了${count}件` : "タスク");
}

export function updateNavigation(container, activeScreen) {
  for (const button of container.querySelectorAll("[data-screen]")) {
    if (button.dataset.screen === activeScreen) {
      button.setAttribute("aria-current", "page");
    } else {
      button.removeAttribute("aria-current");
    }
  }
  updateTaskCount(container, getState());
}
