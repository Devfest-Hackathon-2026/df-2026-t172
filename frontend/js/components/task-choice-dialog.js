import { displayName } from "../patients.js";
import { taskCategory, taskGroups } from "../tasks.js?v=20261110-assign";
import { createIcon } from "./icons.js";
import { element } from "./review-dom.js";

/** assignees は担当の選択肢（看護師の一覧、S-08）。空なら担当の欄を出しません。 */
export function createTaskChoiceDialog({
  host, task, assignment, assignees = [], assignmentNote = "", loadCategories, onConfirm, onClose,
}) {
  const currentCategory = taskCategory(task);
  const dialog = element("dialog", "task-choice-dialog");
  dialog.setAttribute("aria-labelledby", "task-choice-title");
  dialog.setAttribute("aria-describedby", "task-choice-description");
  const form = element("form");
  const header = element("div", "task-choice-heading");
  const title = element("h2", "sheet-title", "タスクを変更");
  title.id = "task-choice-title";
  const close = element("button", "icon-button");
  close.type = "button";
  close.setAttribute("aria-label", "タスク変更を閉じる");
  close.append(createIcon("close"));
  header.append(title, close);
  const body = element("div", "task-choice-body");
  const description = element("div", "task-choice-description");
  description.id = "task-choice-description";
  description.append(element("p", "patient-room", `${task.room}号室　${displayName(task)}`),
    element("p", "task-choice-text", task.text));
  const options = element("fieldset", "task-choice-options");
  options.append(element("legend", "screen-reader-only", "区分を選択"));
  const radios = [];
  for (const group of taskGroups) {
    const row = element("label", "task-choice-option");
    const radio = element("input");
    radio.type = "radio";
    radio.name = "task-urgency";
    radio.value = group.value;
    radio.checked = group.value === task.urgency;
    row.append(radio, element("span", "", group.label));
    if (radio.checked) row.append(element("span", "task-choice-current", "現在"));
    options.append(row);
    radios.push(radio);
  }
  function selectField(caption) {
    const field = element("label", "task-choice-select-field");
    const select = element("select", "input");
    select.setAttribute("aria-label", caption);
    field.append(element("span", "", caption), select);
    return { field, select };
  }
  function appendOption(select, value, caption = value) {
    const option = element("option", "", caption);
    option.value = value;
    select.append(option);
  }
  const { field: categoryField, select: categorySelect } = selectField("分類");
  appendOption(categorySelect, currentCategory);
  const { field: assignmentField, select: assignmentSelect } = selectField("担当");
  for (const { value, label } of assignees) appendOption(assignmentSelect, value, label);
  assignmentSelect.value = assignment;
  assignmentField.hidden = !assignees.length;
  const loadingStatus = element("p", "empty-inline", "分類を読み込み中…");
  loadingStatus.setAttribute("role", "status");
  const categoryError = element("p", "form-error");
  categoryError.setAttribute("role", "alert");
  categoryError.hidden = true;
  const retry = element("button", "secondary-button", "分類一覧を再読み込み");
  retry.type = "button";
  retry.hidden = true;
  const error = element("p", "form-error");
  error.setAttribute("role", "alert");
  error.hidden = true;
  const actions = element("div", "task-choice-actions");
  const cancel = element("button", "secondary-button", "キャンセル");
  cancel.type = "button";
  const submit = element("button", "primary-button", "変更する");
  submit.type = "submit";
  actions.append(cancel, submit);
  body.append(description, options, categoryField, loadingStatus, categoryError, retry, assignmentField,
    ...(assignees.length && assignmentNote
      ? [element("p", "empty-inline task-choice-assignment-note", assignmentNote)] : []), error);
  form.append(header, body, actions);
  dialog.append(form);

  let selected = task.urgency;
  let busy = false;
  let loading = true;
  let categoriesReady = false;
  let closed = false;
  let restoreFocus = true;
  const controller = new AbortController();

  function refresh() {
    form.setAttribute("aria-busy", String(busy));
    loadingStatus.hidden = !loading;
    for (const radio of radios) radio.disabled = busy;
    close.disabled = cancel.disabled = assignmentSelect.disabled = busy;
    categorySelect.disabled = busy || loading || !categoriesReady;
    retry.disabled = busy || loading;
    submit.disabled = busy || (selected === task.urgency && categorySelect.value === currentCategory
      && assignmentSelect.value === assignment);
    submit.textContent = busy ? "変更中…" : "変更する";
    if (busy && dialog.open) dialog.focus();
  }

  async function loadOptions() {
    loading = true;
    categoryError.hidden = retry.hidden = true;
    refresh();
    try {
      const categories = await loadCategories({ signal: controller.signal });
      if (closed || !dialog.open) return;
      const selectedCategory = categorySelect.value;
      categorySelect.replaceChildren();
      for (const value of new Set([currentCategory, ...categories])) appendOption(categorySelect, value);
      categorySelect.value = selectedCategory;
      categoriesReady = true;
    } catch (failure) {
      if (closed || !dialog.open) return;
      categoryError.textContent = failure?.message || "分類の一覧を読み込めませんでした。";
      categoryError.hidden = retry.hidden = false;
    } finally {
      loading = false;
      if (!closed && dialog.open) refresh();
    }
  }

  retry.addEventListener("click", loadOptions);
  options.addEventListener("change", (event) => {
    if (busy || !radios.includes(event.target) || !event.target.checked) return;
    selected = event.target.value;
    error.hidden = true;
    refresh();
  });
  for (const select of [categorySelect, assignmentSelect]) select.addEventListener("change", () => {
    error.hidden = true;
    refresh();
  });
  close.addEventListener("click", () => dialog.close());
  cancel.addEventListener("click", () => dialog.close());
  dialog.addEventListener("cancel", (event) => { if (busy) event.preventDefault(); });
  dialog.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    const controls = [...dialog.querySelectorAll("button:not(:disabled), input:checked:not(:disabled), select:not(:disabled)")]
      .filter((control) => !control.hidden);
    const first = controls[0], last = controls.at(-1);
    if (!first) {
      event.preventDefault();
      dialog.focus();
    } else if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  dialog.addEventListener("click", (event) => {
    if (busy || event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right
      || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submit.disabled || busy || closed) return;
    busy = true;
    error.hidden = true;
    refresh();
    try {
      await onConfirm({ urgency: selected, category: categorySelect.value, assignment: assignmentSelect.value });
      if (!closed && dialog.open) dialog.close();
    } catch (failure) {
      if (closed || !dialog.open) return;
      error.textContent = failure?.message || "変更できませんでした。もう一度お試しください。";
      error.hidden = false;
    } finally {
      busy = false;
      if (!closed && dialog.open) refresh();
    }
  });
  dialog.addEventListener("close", () => {
    closed = true;
    controller.abort();
    dialog.remove();
    onClose({ restoreFocus });
  }, { once: true });

  return {
    open() {
      host.append(dialog);
      refresh();
      dialog.showModal();
      radios.find((radio) => radio.checked)?.focus();
      loadOptions();
    },
    close() {
      restoreFocus = false;
      if (dialog.open) dialog.close();
    },
  };
}
