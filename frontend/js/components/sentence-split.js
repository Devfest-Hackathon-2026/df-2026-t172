import { element } from "./review-dom.js";

function button(label, action, path) {
  const node = element("button", "text-button", label);
  node.type = "button"; node.dataset.splitAction = action; node.dataset.splitPath = path;
  return node;
}

/** 分割の入力途中もメモリだけに置き、親画面の再描画をまたいで保つ。 */
export function appendSentenceTools(row, item, path, session, sentenceLabel, sourceInput) {
  const tools = element("div", "sentence-tools");
  const open = button("文を分ける", "open", path);
  open.setAttribute("aria-label", `${sentenceLabel}を分ける`);
  open.disabled = !session.canSplitSentence(path);
  const slot = element("div", "sentence-split-slot");
  const notify = (focusKey) => row.dispatchEvent(new CustomEvent("review-structure-changed", { bubbles: true, detail: { focusKey } }));
  const updateStatus = () => row.dispatchEvent(new CustomEvent("review-edit-state-changed", { bubbles: true }));
  const showEditor = () => {
    const draft = session.splitEdits.get(item);
    slot.replaceChildren();
    sourceInput.readOnly = Boolean(draft);
    open.hidden = Boolean(draft);
    if (!draft) return;
    const form = element("div", "sentence-split-editor");
    form.setAttribute("role", "group"); form.setAttribute("aria-label", `${sentenceLabel}を分ける`);
    form.append(element("p", "care-plan-help", "前半と後半に分け、元の発言と意味が変わらないようにしてください。"));
    const fields = [];
    for (const [key, text] of [["firstText", "前半"], ["secondText", "後半"]]) {
      const label = element("label", "form-label", text), input = element("textarea", "textarea");
      input.value = draft[key]; input.maxLength = 5000; input.rows = 3;
      input.dataset.reviewField = "split-text"; input.dataset.path = path; input.dataset.focusKey = `split-${key}-${path}`;
      input.setAttribute("aria-label", `${sentenceLabel}の${text}`);
      input.addEventListener("input", () => { draft[key] = input.value; refresh(); });
      fields.push(input); label.append(input); form.append(label);
    }
    const error = element("p", "empty-inline"); error.setAttribute("role", "status");
    const commit = button("この内容で分ける", "commit", path), cancel = button("キャンセル", "cancel", path);
    commit.className = "secondary-button";
    function refresh() {
      const invalid = [draft.firstText, draft.secondText].some((value) => !value.trim() || value.length > 5000);
      commit.disabled = invalid || !session.canSplitSentence(path);
      error.textContent = invalid ? "前半と後半の両方に文章を入力してください。" : "分けた後は再検証が必要です。";
    }
    commit.addEventListener("click", () => {
      const childPath = session.splitSoapSentence(path, draft);
      if (!childPath) return;
      session.splitEdits.delete(item); notify(`care-plan-${childPath}`);
    });
    cancel.addEventListener("click", () => { session.splitEdits.delete(item); showEditor(); updateStatus(); open.focus(); });
    form.append(error, commit, cancel); slot.append(form); refresh();
    for (const field of fields) field.disabled = !session.canSplitSentence(path);
  };
  open.addEventListener("click", () => {
    if (!session.canSplitSentence(path)) return;
    session.splitEdits.set(item, { firstText: item.text, secondText: "" }); showEditor(); updateStatus();
    slot.querySelector("textarea")?.focus();
  });
  tools.append(open);
  const split = session.splits.get(item);
  if (split && session.draft.soap[split.part].includes(split.source)) {
    const undo = button("分けを戻す", "undo", path);
    undo.setAttribute("aria-label", `${sentenceLabel}の分けを戻す`);
    undo.disabled = !session.canUndoSplit(path);
    undo.addEventListener("click", () => {
      if (!session.canUndoSplit(path) || slot.querySelector("[data-undo-confirm]")) return;
      const confirmation = element("div", "sentence-split-editor");
      confirmation.dataset.undoConfirm = "";
      confirmation.setAttribute("role", "group");
      confirmation.setAttribute("aria-label", "分けを戻す確認");
      confirmation.append(element("p", "", "分ける前の文章に戻します。分けた後の文章の修正と、後半の計画選択は失われます。"));
      const accept = button("分ける前へ戻す", "undo-accept", path), cancel = button("戻さない", "undo-cancel", path);
      accept.className = "secondary-button";
      accept.addEventListener("click", () => {
        if (!session.canUndoSplit(path)) return;
        const record = session.splits.get(item), source = record.source, part = record.part;
        session.splitEdits.delete(item);
        if (session.undoSplit(path)) notify(`care-plan-soap.${part}[${session.draft.soap[part].indexOf(source)}]`);
      });
      cancel.addEventListener("click", () => { confirmation.remove(); undo.focus(); });
      confirmation.append(accept, cancel); slot.append(confirmation); cancel.focus();
    });
    tools.append(undo);
  }
  row.append(tools, slot); showEditor();
}
