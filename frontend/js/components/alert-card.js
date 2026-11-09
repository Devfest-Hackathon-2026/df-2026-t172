import { element, reviewButton } from "./review-dom.js";
import { renderEvidence, utteranceLabel } from "./evidence-card.js";

function renderCheckMessage(check, references, session) {
  const message = check.message.replace(/^(?:二段目|二段階目)[：:]/u, "AI の再確認：")
    .replace(/\b(u\d+)\b[ \t]+(?=[はがをにとのもへで])/gu, "$1");
  const paragraph = element("p", "alert-message");
  let end = 0;
  for (const match of message.matchAll(/\bu\d+\b/gu)) {
    paragraph.append(message.slice(end, match.index));
    const id = match[0];
    const row = references && [...references.querySelectorAll("[data-utterance-id]")]
      .find((node) => node.dataset.utteranceId === id);
    if (row) {
      const button = element("button", "utterance-reference", utteranceLabel(id));
      button.type = "button";
      button.setAttribute("aria-label", `${utteranceLabel(id)}を確認`);
      button.setAttribute("aria-controls", references.id);
      button.addEventListener("click", () => {
        session.recordEvidenceTap();
        references.open = true;
        for (const node of references.querySelectorAll(".is-reference-target")) node.classList.remove("is-reference-target");
        row.classList.add("is-reference-target");
        row.focus({ preventScroll: true });
        row.scrollIntoView({ block: "nearest" });
      });
      paragraph.append(button);
    } else paragraph.append(utteranceLabel(id));
    end = match.index + id.length;
  }
  paragraph.append(message.slice(end));
  return paragraph;
}

export function pathLabel(path, session) {
  const target = session.target(path);
  if (path.startsWith("vitals[")) return target?.item ?? "バイタル";
  if (path.startsWith("soap.S")) return "SOAP S";
  if (path.startsWith("soap.O")) return "SOAP O";
  if (path.startsWith("requests")) return path.endsWith(".cue") ? "依頼の手がかり" : "患者からの依頼";
  if (path.startsWith("manual_needed")) return "手で入力が必要（薬など）";
  return "医師への確認";
}

export function renderAlertCard(path, checks, session) {
  const stop = checks.some((check) => check.level === "stop");
  const card = element("article", "alert-card");
  card.id = `check-${path}`;
  card.tabIndex = -1;
  card.setAttribute("aria-label", `${pathLabel(path, session)}の確認事項`);
  card.dataset.level = stop ? "stop" : "warn";
  card.dataset.alertPath = path;
  const heading = element("div", "alert-heading");
  heading.append(element("h3", "alert-title", pathLabel(path, session)));
  heading.append(element("span", "alert-level", stop ? "要確認" : "注意"));
  const target = session.target(path);
  card.append(heading, element("p", "alert-target", target.value ?? target.text));
  const referencedIds = [...new Set([
    ...(target.evidence ?? []),
    ...checks.flatMap((check) => check.message.match(/\bu\d+\b/gu) ?? []),
  ])].filter((id) => session.utterances.some((utterance) => utterance.id === id));
  const references = referencedIds.length ? renderEvidence(referencedIds, session, `alert-${path}`) : null;
  for (const check of checks) card.append(renderCheckMessage(check, references, session));
  if (references) {
    references.querySelector("summary").textContent = "参照した発言を確認";
    card.append(references);
  }
  if (stop) {
    const buttons = element("div", "decision-buttons");
    for (const [action, label] of [["keep", "残す"], ["delete", "消す"]]) {
      const button = reviewButton(label, "decide");
      button.dataset.path = path;
      button.dataset.decision = action;
      button.dataset.focusKey = `decision-${path}-${action}`;
      button.setAttribute("aria-pressed", String(session.action(path) === action));
      button.setAttribute("aria-label", `${pathLabel(path, session)}の対象を${label}`);
      buttons.append(button);
    }
    card.append(buttons);
  }
  if (checks.some((check) => check.code === "multiple_values")) {
    const confirm = reviewButton("この値を使用", "confirm-multiple");
    confirm.dataset.path = path;
    confirm.dataset.focusKey = `multiple-${path}`;
    card.append(confirm);
  }
  return card;
}
