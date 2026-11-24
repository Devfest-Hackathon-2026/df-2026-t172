import { renderRecordSummary } from "./record-summary.js?v=20261121-context-help";
import { element } from "./review-dom.js";

/** 確定する範囲を表示用に取り出す。この時点では保存のIDも作らない。 */
export function recordConfirmationPreview(session) {
  const { draft, patient } = session;
  const isDeleted = (path) => session.action(path) === "delete";
  const retained = (items, path) => items.filter((_, index) => !isDeleted(`${path}[${index}]`));

  return {
    name: patient.name,
    full_name: patient.full_name,
    room: patient.room,
    bed: patient.bed,
    care_plans: patient.care_plans,
    vitals: retained(draft.vitals, "vitals"),
    soap: { ...draft.soap, S: retained(draft.soap.S, "soap.S"), O: retained(draft.soap.O, "soap.O") },
    requests: draft.requests.flatMap((request, index) => {
      const path = `requests[${index}]`;
      if (isDeleted(path)) return [];
      return [isDeleted(`${path}.cue`) ? { ...request, cue: null, urgency: "none" } : request];
    }),
    manual_needed: retained(draft.manual_needed, "manual_needed"),
    doctor_questions: retained(draft.doctor_questions, "doctor_questions"),
  };
}

export function createRecordConfirmationDialog({ host, session, onConfirm, onClose }) {
  return createSummaryConfirmationDialog({
    host, onConfirm, onClose, record: recordConfirmationPreview(session),
    question: "以下の内容で確定しますか？", confirmLabel: "確定する", regionLabel: "確定する内容",
  });
}

export function createSummaryConfirmationDialog({ host, record, onConfirm, onClose, question, confirmLabel, regionLabel }) {
  const dialog = element("dialog", "record-confirmation-dialog");
  dialog.setAttribute("aria-labelledby", "record-confirmation-title");
  const form = element("form");
  const header = element("div", "task-choice-heading");
  const title = element("h2", "sheet-title", question);
  title.id = "record-confirmation-title";
  header.append(title);

  const body = element("div", "task-choice-body");
  body.tabIndex = 0;
  body.setAttribute("role", "region");
  body.setAttribute("aria-label", regionLabel);
  body.append(renderRecordSummary(record));

  const actions = element("div", "task-choice-actions");
  const back = element("button", "secondary-button", "戻る");
  back.type = "button";
  back.autofocus = true;
  const confirm = element("button", "primary-button", confirmLabel);
  confirm.type = "submit";
  actions.append(back, confirm);
  form.append(header, body, actions);
  dialog.append(form);

  let restoreFocus = true;
  back.addEventListener("click", () => dialog.close());
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!dialog.open) return;
    restoreFocus = false;
    dialog.close();
    onConfirm();
  });
  dialog.addEventListener("close", () => {
    dialog.remove();
    onClose({ restoreFocus });
  }, { once: true });

  return {
    open() {
      host.append(dialog);
      dialog.showModal();
    },
    close() {
      restoreFocus = false;
      if (dialog.open) dialog.close();
    },
  };
}
