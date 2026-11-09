import { vitalItems } from "../records.js";
import { element, panel } from "./review-dom.js";
import { renderEvidence } from "./evidence-card.js";
import { markCheckTarget } from "./review-entry.js";

export function renderVitalCard(session) {
  const section = panel("バイタル");
  const grid = element("div", "vital-grid");
  for (const [itemNumber, definition] of vitalItems.entries()) {
    const matches = session.draft.vitals.map((vital, index) => ({ vital, index }))
      .filter(({ vital }) => vital.item === definition.item);
    const rows = matches.length ? matches : [{ vital: null, index: null }];
    for (const [occurrence, { vital, index }] of rows.entries()) {
      const field = element("div", "vital-field");
      field.dataset.vitalItem = definition.item;
      markCheckTarget(field, index === null ? null : `vitals[${index}]`);
      const label = element("label", "form-label", definition.item + (occurrence ? `（${occurrence + 1}件目）` : ""));
      const id = `review-vital-${itemNumber}-${occurrence}`;
      label.htmlFor = id;
      const inputRow = element("div", "vital-input-row");
      const input = element("input", "input");
      input.id = id;
      input.type = "text";
      input.inputMode = definition.item === "血圧" ? "text" : "decimal";
      input.autocomplete = "off";
      input.maxLength = 100;
      input.value = vital?.value ?? "";
      input.placeholder = definition.optional ? "任意" : "未入力";
      input.dataset.reviewField = "vital";
      input.dataset.vitalItem = definition.item;
      input.dataset.vitalIndex = index === null ? "" : String(index);
      input.dataset.focusKey = `vital-${itemNumber}-${occurrence}`;
      if (index !== null) input.disabled = session.action(`vitals[${index}]`) === "delete";
      inputRow.append(input, element("span", "vital-unit", definition.unit));
      field.append(label, inputRow);
      if (vital?.source === "conversation") {
        const roots = renderEvidence(vital.evidence, session, `vital-evidence-${index}`);
        roots.dataset.vitalEvidence = "";
        field.append(roots);
      }
      if (index !== null && session.action(`vitals[${index}]`) === "delete") {
        field.append(element("span", "delete-note", "確定時に削除"));
      }
      grid.append(field);
    }
  }
  section.append(grid);
  return section;
}
