import { element } from "./review-dom.js";

export function renderUsageGuide() {
  const dialog = element("dialog", "usage-guide");
  dialog.id = "usage-guide";
  dialog.setAttribute("aria-labelledby", "usage-guide-title");
  const root = element("div", "guide-body");
  const title = element("h2", "guide-title", "記録までの3ステップ");
  title.id = "usage-guide-title";
  const close = element("button", "text-button guide-close", "閉じる");
  close.type = "button";
  close.autofocus = true;
  close.addEventListener("click", () => dialog.close());
  const heading = element("header", "guide-heading");
  heading.append(title, close);
  const list = element("ol", "guide-steps");
  for (const [title, text] of [
    ["患者を選んで入力", "録音、またはテキストで入力します。録音前に同意を確認してください。"],
    ["根拠を見て確認・修正", "数値や文章を元の発言と比べます。赤い枠の内容は、残すか消すか選びます。"],
    ["内容を確認して確定", "「確定」を押すと、保存前の確認画面が開きます。「戻る」で修正に戻り、「確定する」で保存します。保存後はカルテ用の文章をコピーできます。"],
  ]) {
    const item = element("li");
    item.append(element("strong", "", title), element("p", "", text));
    list.append(item);
  }
  root.append(list);
  const details = element("details", "guide-details");
  details.append(element("summary", "", "看護計画の選択・文の分け方"),
    element("p", "", "S・Oの文ごとに看護計画を選べます。最初は「計画外」です。計画だけの変更では再検証は不要です。"),
    element("p", "", "複数の話題を含む文は「文を分ける」で前半・後半に分けられます。後半は「計画外」になるため、必要な計画を選び直してください。分けた後は再検証します。"),
    element("p", "", "後半の「分けを戻す」から取消できます。確認して戻すと、分けた後の文章の修正と後半の計画選択は失われます。保存後はこの取消操作は使えません。"));
  root.append(details,
    element("h3", "guide-subtitle", "保存した記録を直すには"),
    element("p", "guide-note", "画面下の「会話記録」から記録を開き、下部の「編集」を押します。修正後は「変更を確認」で内容を確認し、「変更を保存」を押してください。依頼は「タスク」で確認できます。"));
  dialog.append(heading, root);
  return dialog;
}
