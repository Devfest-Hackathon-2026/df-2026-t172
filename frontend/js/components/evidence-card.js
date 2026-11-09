import { element } from "./review-dom.js";

const speakers = { nurse: "看護師", patient: "患者", unknown: "話者不明" };

export function utteranceLabel(id) {
  const number = /^u(\d+)$/u.exec(id)?.[1];
  return number ? `発言${number}` : `発言 ${id}`;
}

export function renderUtterance(utterance, session) {
  const row = element("div", "utterance");
  row.dataset.utteranceId = utterance.id;
  row.tabIndex = -1;
  row.append(element("p", "utterance-meta", `${utteranceLabel(utterance.id)}　${speakers[utterance.speaker]}`));
  row.append(element("p", "utterance-text", utterance.text));
  // mockの発言時刻は見本の会話の時刻で、今回の録音との対応はありません。
  if (session.audioUrl && session.mode !== "mock" && Number.isFinite(utterance.start) && Number.isFinite(utterance.end)) {
    const audio = element("audio", "evidence-audio");
    audio.controls = true;
    audio.preload = "none";
    audio.src = session.audioUrl;
    audio.setAttribute("aria-label", `${utteranceLabel(utterance.id)}、${speakers[utterance.speaker]}の音声`);
    const start = Number.isFinite(utterance.start) ? Math.max(0, utterance.start) : 0;
    const end = Number.isFinite(utterance.end) && utterance.end > start ? utterance.end : null;
    audio.addEventListener("play", () => {
      for (const other of document.querySelectorAll("audio")) if (other !== audio) other.pause();
      if (audio.currentTime < start || (end && audio.currentTime >= end)) {
        try { audio.currentTime = start; } catch { /* 区間へ移れない形式では全体を再生します。 */ }
      }
    });
    audio.addEventListener("timeupdate", () => {
      if (end && audio.currentTime >= end) audio.pause();
    });
    row.append(audio);
  }
  return row;
}

export function renderEvidence(ids, session, key) {
  const details = element("details", "evidence-details");
  details.id = `evidence-${key}`;
  details.dataset.detailsKey = key;
  const summary = element("summary", "evidence-toggle", ids.length ? `根拠を確認（${ids.map(utteranceLabel).join("・")}）` : "根拠なし");
  summary.addEventListener("click", () => session.recordEvidenceTap());
  details.append(summary);
  for (const id of ids) {
    const utterance = session.utterances.find((item) => item.id === id);
    details.append(utterance ? renderUtterance(utterance, session)
      : element("p", "form-error", "該当する発言が見つかりません"));
  }
  return details;
}
