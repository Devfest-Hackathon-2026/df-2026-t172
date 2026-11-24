import { element } from "./review-dom.js";

export function renderCarePlanSelect(item, path, session, sentenceLabel) {
  const label = element("label", "care-plan-label", "看護計画");
  const select = element("select", "input care-plan-select");
  select.dataset.reviewField = "care-plan";
  select.dataset.path = path;
  select.dataset.focusKey = `care-plan-${path}`;
  select.setAttribute("aria-label", `${sentenceLabel}の看護計画`);
  for (const plan of [...session.patient.care_plans, { id: "", label: "計画外" }]) {
    const option = element("option", "", plan.label); option.value = plan.id; select.append(option);
  }
  select.value = item.plan_id ?? "";
  label.append(select);
  return label;
}
