import { displayName, loadPatients } from "../patients.js";
import { createIcon } from "./icons.js";

export function createPatientSheet({ host, onSelect, onConsent, onClose, inputMethod = "audio" }) {
  const dialog = document.createElement("dialog");
  dialog.className = "patient-sheet";
  dialog.setAttribute("aria-labelledby", "patient-sheet-title");
  const handle = document.createElement("div");
  handle.className = "sheet-handle";
  handle.setAttribute("aria-hidden", "true");
  const header = document.createElement("div");
  header.className = "sheet-header";
  const title = document.createElement("h2");
  title.id = "patient-sheet-title";
  title.className = "sheet-title";
  title.textContent = "患者を選択";
  const closeButton = document.createElement("button");
  closeButton.type = "button";
  closeButton.className = "icon-button";
  closeButton.setAttribute("aria-label", "患者選択を閉じる");
  closeButton.append(createIcon("close"));
  closeButton.addEventListener("click", () => dialog.close());
  header.append(title, closeButton);

  const list = document.createElement("div");
  list.className = "patient-list";
  const footer = document.createElement("div");
  footer.className = "sheet-footer";
  let firstSpeaker = "auto";
  const speakers = document.createElement("fieldset");
  speakers.className = "speaker-options";
  const legend = document.createElement("legend");
  legend.textContent = "最初に話す人";
  speakers.append(legend);
  const choices = document.createElement("div");
  choices.className = "speaker-choices";
  for (const [value, text] of [["auto", "自動"], ["nurse", "看護師"], ["patient", "患者"]]) {
    const label = document.createElement("label");
    label.className = "speaker-choice";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "first_speaker";
    input.value = value;
    input.checked = value === firstSpeaker;
    const caption = document.createElement("span");
    caption.textContent = text;
    input.addEventListener("change", () => { if (input.checked) firstSpeaker = value; });
    label.append(input, caption);
    choices.append(label);
  }
  speakers.append(choices);
  footer.append(speakers);
  const consent = document.createElement("button");
  consent.type = "button";
  consent.className = "primary-button";
  consent.textContent = inputMethod === "audio" ? "同意を得ました" : "入力へ";
  consent.disabled = true;
  footer.append(consent);
  dialog.append(handle, header, list, footer);

  let patients = [];
  let selectedId = null;
  let confirmed = false;
  let requestController;
  let closed = false;

  function position() {
    const rect = document.querySelector(".app-shell").getBoundingClientRect();
    dialog.style.left = `${rect.left}px`;
    dialog.style.bottom = `${Math.max(0, window.innerHeight - rect.bottom)}px`;
    dialog.style.width = `${rect.width}px`;
    dialog.style.maxHeight = `${Math.min(window.innerHeight * .83, rect.height - 24)}px`;
  }

  function renderPatients() {
    if (!patients.length) {
      const empty = document.createElement("p");
      empty.className = "sheet-message";
      empty.textContent = "患者がいません";
      list.replaceChildren(empty);
      return;
    }
    const fieldset = document.createElement("fieldset");
    fieldset.className = "patient-options";
    const legend = document.createElement("legend");
    legend.className = "screen-reader-only";
    legend.textContent = "患者";
    fieldset.append(legend);
    for (const patient of patients) {
      const option = document.createElement("label");
      option.className = "patient-option";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "patient_id";
      input.value = patient.id;
      input.className = "screen-reader-only";
      input.setAttribute("aria-label", `${patient.room}号室 ベッド${patient.bed} ${displayName(patient)}`);
      const info = document.createElement("span");
      info.className = "patient-info";
      const room = document.createElement("span");
      room.className = "patient-room";
      room.textContent = `${patient.room}号室　ベッド${patient.bed}`;
      const name = document.createElement("strong");
      name.className = "patient-name";
      name.textContent = displayName(patient);
      info.append(room, name);
      const mark = document.createElement("span");
      mark.className = "patient-mark";
      mark.append(createIcon("check"));
      option.append(input, info, mark);
      input.addEventListener("change", () => {
        if (!input.checked) return;
        selectedId = patient.id;
        for (const row of fieldset.querySelectorAll(".patient-option")) {
          row.classList.toggle("selected", row.querySelector("input").checked);
        }
        consent.disabled = false;
        onSelect(patient);
      });
      fieldset.append(option);
    }
    list.replaceChildren(fieldset);
  }

  async function refresh() {
    requestController?.abort();
    const controller = new AbortController();
    requestController = controller;
    selectedId = null;
    patients = [];
    consent.disabled = true;
    onSelect(null);
    const loading = document.createElement("div");
    loading.className = "sheet-message";
    loading.setAttribute("role", "status");
    loading.textContent = "読み込み中…";
    list.replaceChildren(loading);
    list.setAttribute("aria-busy", "true");
    try {
      const result = await loadPatients({ signal: controller.signal });
      if (closed || controller.signal.aborted) return;
      patients = result;
      renderPatients();
    } catch (error) {
      if (closed || controller.signal.aborted || error.status === 401) return;
      const message = document.createElement("p");
      message.className = "form-error sheet-message";
      message.setAttribute("role", "alert");
      message.textContent = error.message;
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "secondary-button";
      retry.textContent = "再試行";
      retry.addEventListener("click", refresh);
      list.replaceChildren(message, retry);
    } finally {
      if (requestController === controller) list.setAttribute("aria-busy", "false");
    }
  }

  consent.addEventListener("click", () => {
    const patient = patients.find((item) => item.id === selectedId);
    if (!patient || consent.disabled) return;
    if (onConsent(patient, { firstSpeaker }) === false) return;
    confirmed = true;
    dialog.close();
  });

  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right
      || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  });

  dialog.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    const radios = [...dialog.querySelectorAll('input[type="radio"]')];
    const activeRadios = new Map();
    for (const radio of radios) {
      if (!activeRadios.has(radio.name) || radio.checked) activeRadios.set(radio.name, radio);
    }
    const controls = [...dialog.querySelectorAll("button:not(:disabled), input:not(:disabled)")]
      .filter((control) => control.type !== "radio" || control === activeRadios.get(control.name))
      .filter((control) => !control.closest("[hidden]") && !control.matches(":disabled"));
    const first = controls[0];
    const last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  });

  dialog.addEventListener("close", () => {
    closed = true;
    requestController?.abort();
    window.removeEventListener("resize", position);
    dialog.remove();
    patients = [];
    onClose({ confirmed });
  }, { once: true });

  return {
    open() {
      host.append(dialog);
      position();
      dialog.showModal();
      window.addEventListener("resize", position);
      refresh();
    },
    close() { if (dialog.open) dialog.close(); },
  };
}
