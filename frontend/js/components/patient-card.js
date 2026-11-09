import { displayName } from "../patients.js";
import { element } from "./review-dom.js";
import { createIcon } from "./icons.js?v=20261109-navy";

export function renderPatientCard(session) {
  const { patient, patientMatch } = session;
  const card = element("section", "patient-card");
  card.dataset.match = patientMatch.level;
  const heading = element("div", "patient-card-heading");
  const info = element("div");
  info.append(element("p", "patient-room", `${patient.room}号室　ベッド${patient.bed}`));
  info.append(element("h2", "review-patient-name", displayName(patient)));
  const labels = { ok: "一致", confirm: "照合できず", stop: "食い違いあり" };
  const badge = element("span", "match-badge");
  badge.append(createIcon({ ok: "check", confirm: "warning", stop: "alert" }[patientMatch.level]),
    document.createTextNode(labels[patientMatch.level]));
  heading.append(info, badge);
  card.append(heading);
  for (const reason of patientMatch.reasons) card.append(element("p", "match-reason", reason));
  if (patientMatch.level !== "ok") {
    const label = element("label", "patient-confirm");
    const checkbox = element("input");
    checkbox.type = "checkbox";
    checkbox.checked = session.patientConfirmed;
    checkbox.dataset.reviewField = "patient-confirmed";
    checkbox.dataset.focusKey = "patient-confirmed";
    label.append(checkbox, document.createTextNode("この患者で正しい"));
    card.append(label);
  }
  return card;
}
