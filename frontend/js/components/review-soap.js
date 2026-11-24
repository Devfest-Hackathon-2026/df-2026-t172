import { element, panel } from "./review-dom.js";
import { addEntryButton, renderReviewEntry } from "./review-entry.js?v=20261121-context-help";
import { groupSoapByPlan } from "../care-plans.js?v=20261121-context-help";

export function renderSoap(session) {
  const section = panel("看護記録");
  section.append(element("p", "care-plan-help", session.patient.care_plans.length
    ? "S・Oの文に看護計画を選んでください。当てはまらない文は計画外に残せます。"
    : "この患者に登録された看護計画はありません。S・Oの文は計画外として確認できます。"));
  const help = element("details", "review-plan-guide");
  help.dataset.detailsKey = "care-plan-help";
  help.append(
    element("summary", "", "？ 看護計画の使い方"),
    element("p", "care-plan-help", "話題が混ざった文は「文を分ける」を使います。後半は「計画外」になるので、必要なら計画を選んでください。元に戻すには、後半の「分けを戻す」を押します。"),
  );
  section.append(help);
  section.append(element("p", "care-plan-change-status screen-reader-only", ""));
  section.lastChild.setAttribute("role", "status");
  section.lastChild.dataset.planChangeStatus = "";
  for (const group of groupSoapByPlan(session.draft.soap, session.patient.care_plans)) {
    const block = element("section", "care-plan-group");
    block.dataset.planGroup = group.id ?? "";
    block.append(element("h3", "care-plan-heading", group.id === null ? "計画外" : `看護計画：${group.label}`));
    if (!group.entries.length) block.append(element("p", "empty-inline", "まだ文はありません"));
    for (const part of ["S", "O"]) {
      const entries = group.entries.filter((entry) => entry.part === part);
      if (!entries.length) continue;
      block.append(element("h4", "soap-title", part === "S" ? "S　患者の訴え" : "O　観察・測定"));
      for (const { item, path, index } of entries) block.append(renderReviewEntry(item, path, session, {
        part, index, label: `${part} ${index + 1}文目`, evidenceKey: `soap-evidence-${part}-${index}`, className: "soap-sentence",
      }));
    }
    if (group.id === null) {
      block.append(addEntryButton("soap.S", "＋ Sの文を追加", session), addEntryButton("soap.O", "＋ Oの文を追加", session));
    }
    section.append(block);
  }
  for (const [part, text] of [["A", "アセスメント"], ["P", "計画"]]) {
    const label = element("label", "soap-group");
    label.append(element("span", "soap-title", `${part}　${text}`), element("span", "empty-inline", "看護師が記入"));
    const input = element("textarea", "textarea");
    input.value = session.draft.soap[part]; input.maxLength = 5000;
    input.dataset.reviewField = "soap"; input.dataset.part = part; input.dataset.focusKey = `soap-${part}`;
    input.setAttribute("aria-label", `${part}　${text}`); label.append(input); section.append(label);
  }
  return section;
}
