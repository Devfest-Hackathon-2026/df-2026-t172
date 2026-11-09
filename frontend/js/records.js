import { ApiError, createDraft, postRecord, verifyDraft } from "./api.js";
import { audioFilename, MAX_AUDIO_BYTES, MAX_AUDIO_SECONDS } from "./recorder.js";
import { reportedBy } from "./assignment.js";

export function isoJst(date = new Date()) {
  return `${new Date(date.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, -1)}+09:00`;
}

function createConfirmId() {
  const bytes = crypto.getRandomValues(new Uint8Array(12));
  return `c_${Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

export const vitalItems = Object.freeze([
  { item: "体温", unit: "℃" },
  { item: "血圧", unit: "mmHg" },
  { item: "脈拍", unit: "回/分" },
  { item: "呼吸数", unit: "回/分" },
  { item: "SpO2", unit: "%" },
  { item: "血糖", unit: "mg/dL", optional: true },
]);
const requiredVitals = vitalItems.filter((vital) => !vital.optional).map((vital) => vital.item);
const clone = (value) => structuredClone(value);
const text = (value) => typeof value === "string";
const evidence = (value) => Array.isArray(value) && value.length <= 3 && value.every(text);
const sentence = (value) => value && text(value.text) && evidence(value.evidence);
const invalid = () => new ApiError("下書きの形式が正しくありません。", { code: "invalid_response" });
const addableKinds = ["soap.S", "soap.O", "requests", "doctor_questions", "manual_needed"];
function validateFirstSpeaker(value) {
  if (!["auto", "nurse", "patient"].includes(value)) {
    throw new ApiError("最初に話す人を選択してください。", { code: "invalid_first_speaker" });
  }
}
const normalizedText = (value) => value.normalize("NFKC").replace(/\s+/gu, "").replace(/[。．.、,！!？?]+$/gu, "");
const elementList = (draft, kind) => !addableKinds.includes(kind) ? null
  : kind.startsWith("soap.") ? draft.soap[kind.slice(-1)] : draft[kind];

function targetAt(draft, path) {
  const match = /^(vitals|soap\.S|soap\.O|requests|manual_needed|doctor_questions)\[(\d+)\](\.cue)?$/.exec(path);
  if (!match || (match[3] && match[1] !== "requests")) return null;
  const list = match[1].startsWith("soap.") ? draft.soap[match[1].slice(5)] : draft[match[1]];
  const target = list?.[Number(match[2])];
  return match[3] ? target?.cue ?? null : target ?? null;
}

function validChecks(checks, draft) {
  return Array.isArray(checks) && checks.every((check) => check
    && ["stop", "warn"].includes(check.level) && text(check.path)
    && text(check.code) && text(check.message) && targetAt(draft, check.path));
}

function validMissing(missing) {
  return Array.isArray(missing) && missing.every((item) => requiredVitals.includes(item));
}

function validateResponse(data, expectedPatientId) {
  const draft = data?.draft;
  if (!data?.patient || data.patient.id !== expectedPatientId
    || ["id", "room", "bed", "name"].some((key) => !text(data.patient[key]))
    || !["mock", "live"].includes(data.mode) || !["audio", "text"].includes(data.input)
    || !["ok", "confirm", "stop"].includes(data.patient_match?.level)
    || !Array.isArray(data.patient_match.reasons) || !data.patient_match.reasons.every(text)
    || !Array.isArray(data.utterances) || data.utterances.length > 200
    || data.utterances.some((u) => !u || !text(u.id) || !text(u.text)
      || !["nurse", "patient", "unknown"].includes(u.speaker))
    || new Set(data.utterances.map((u) => u.id)).size !== data.utterances.length
    || !draft || !Array.isArray(draft.vitals) || draft.vitals.length > 30
    || draft.vitals.some((v) => !v || !vitalItems.some((item) => item.item === v.item)
      || !text(v.value) || !evidence(v.evidence) || !["conversation", "manual"].includes(v.source))
    || !draft.soap || ["S", "O"].some((part) => !Array.isArray(draft.soap[part])
      || draft.soap[part].length > 50 || !draft.soap[part].every(sentence))
    || ["requests", "manual_needed", "doctor_questions"].some((key) => !Array.isArray(draft[key])
      || draft[key].length > 30 || !draft[key].every(sentence))
    || draft.requests.some((request) => !["said_urgent", "timed", "none"].includes(request.urgency)
      || (request.cue && (!text(request.cue.text) || !evidence(request.cue.evidence))))
    || !validChecks(data.checks, draft) || !validMissing(data.missing)
    || !Array.isArray(data.entail_seals)
    || (data.draft_token !== undefined && !text(data.draft_token))) throw invalid();
}

/** 同じ音声入力をmock/liveの両方へ送り、認識や下書きの作成はサーバーに任せます。 */
export async function createAudioReview(patient, recording, { consentConfirmed = false, firstSpeaker = "auto", ...options } = {}) {
  if (!consentConfirmed) throw new ApiError("録音の同意を確認してください。", { status: 400, code: "consent_required" });
  validateFirstSpeaker(firstSpeaker);
  if (!(recording?.audio instanceof Blob) || !recording.audio.size || recording.audio.size > MAX_AUDIO_BYTES
    || !Number.isFinite(recording.durationSeconds) || recording.durationSeconds <= 0 || recording.durationSeconds > MAX_AUDIO_SECONDS
    || !(recording.startedAt instanceof Date) || !Number.isFinite(recording.startedAt.getTime())
    || !(recording.stoppedAt instanceof Date) || !Number.isFinite(recording.stoppedAt.getTime())) {
    throw new ApiError("録音データを確認できません。録り直してください。", { code: "invalid_recording" });
  }
  const body = new FormData();
  body.append("patient_id", patient.id);
  body.append("audio", recording.audio, audioFilename(recording.audio.type));
  body.append("consent_confirmed", "true");
  body.append("duration_seconds", String(recording.durationSeconds));
  body.append("first_speaker", firstSpeaker);
  const data = await createDraft(body, options);
  if (options.signal?.aborted) throw new ApiError("通信を中止しました。", { code: "aborted" });
  if (data.input !== "audio") throw invalid();
  return new ReviewSession(data, { expectedPatientId: patient.id, audio: recording.audio,
    timing: { recording_started: isoJst(recording.startedAt), recording_stopped: isoJst(recording.stoppedAt) } });
}

export function transcriptError(transcript) {
  if (typeof transcript !== "string" || !transcript.trim()) return "会話を入力してください。";
  if ([...transcript].length > 5000) return "会話は5,000文字までです。";
  const lines = transcript.split(/\r?\n/).filter((line) => line.trim());
  if (lines.length > 200) return "発言は200件までです。";
  if (lines.some((line) => /^(看護師|患者)\s*[:：]\s*$/.test(line.trim()))) return "発言内容を入力してください。";
  return "";
}

export async function createTextReview(patient, transcript, { firstSpeaker = "auto", ...options } = {}) {
  validateFirstSpeaker(firstSpeaker);
  const error = transcriptError(transcript);
  if (error) throw new ApiError(error, { code: "invalid_transcript" });
  const data = await createDraft({ patient_id: patient.id, transcript, first_speaker: firstSpeaker }, options);
  if (options.signal?.aborted) throw new ApiError("通信を中止しました。", { code: "aborted" });
  if (data.input !== "text") throw invalid();
  return new ReviewSession(data, { expectedPatientId: patient.id });
}

/** 下書き・会話全文・音声はこのセッションのメモリ内だけで保持します。 */
export class ReviewSession {
  constructor(data, { expectedPatientId = data?.patient?.id, audio = null, timing = {} } = {}) {
    validateResponse(data, expectedPatientId);
    this.patient = clone(data.patient);
    this.patientMatch = clone(data.patient_match);
    this.input = data.input;
    this.mode = data.mode;
    this.utterances = clone(data.utterances);
    this.draft = clone(data.draft);
    this.addedElements = new Set();
    this.originalAiTexts = new Set(addableKinds.flatMap((kind) => elementList(this.draft, kind)
      .filter((item) => item.added_by !== "nurse").map((item) => normalizedText(item.text))));
    // A・Pは看護師だけが書きます。生成側に値があっても引き継ぎません。
    this.draft.soap.A = "";
    this.draft.soap.P = "";
    this.checks = clone(data.checks);
    this.missing = clone(data.missing);
    // サーバー署名は解釈・生成せず、そのまま次の確定処理へ引き継ぎます。
    this.seals = clone(data.entail_seals);
    // 下書きの識別用署名も解釈せず保持し、再検証では置き換えません。
    this.draftToken = data.draft_token ?? null;
    this.rememberVerifiedVitals();
    this.patientConfirmed = false;
    this.decisions = new Map();
    this.multipleConfirmed = new Map();
    this.revision = 0;
    this.verifiedRevision = 0;
    this.needsEntail = false;
    this.status = "verified";
    this.error = "";
    this.disposed = false;
    this.counts = { edited: 0, evidence_taps: 0 };
    this.editedPaths = new Set();
    this.audio = audio;
    this.audioUrl = audio ? URL.createObjectURL(audio) : null;
    this.timing = {
      recording_started: timing.recording_started ?? null,
      recording_stopped: timing.recording_stopped ?? null,
      draft_shown: isoJst(),
      confirmed: null,
    };
    this.confirmId = null;
    this.pendingConfirmation = null;
    this.savePromise = null;
    this.saveStatus = "idle";
    this.saveError = "";
  }

  isLocked() {
    return this.saveStatus === "saving" || this.saveStatus === "uncertain";
  }

  canRetrySave() {
    return !this.disposed && this.saveStatus === "uncertain" && this.pendingConfirmation !== null;
  }

  canSwapSpeakers() {
    return !this.disposed && !this.isLocked() && this.status !== "verifying"
      && this.utterances.some((utterance) => ["nurse", "patient"].includes(utterance.speaker));
  }

  swapSpeakers() {
    if (!this.canSwapSpeakers()) return false;
    this.utterances = this.utterances.map((utterance) => ({
      ...utterance,
      speaker: utterance.speaker === "nurse" ? "patient" : utterance.speaker === "patient" ? "nurse" : "unknown",
    }));
    this.touch("utterances", { entail: true });
    // 話者が変わると根拠の意味も変わるため、以前の確認を使い回しません。
    this.seals = [];
    this.decisions.clear();
    this.multipleConfirmed.clear();
    this.verifiedVitalData.clear();
    return true;
  }

  resetSaveError() {
    if (this.disposed || this.isLocked()) return;
    this.saveStatus = "idle";
    this.saveError = "";
    this.pendingConfirmation = null;
    this.timing.confirmed = null;
  }

  confirmPatient(confirmed) {
    if (this.disposed || this.isLocked()) return;
    this.patientConfirmed = Boolean(confirmed);
    this.resetSaveError();
  }

  fingerprint(path) {
    return JSON.stringify([targetAt(this.draft, path), this.checks
      .filter((check) => check.path === path)
      .map(({ level, code, message }) => [level, code, message]).sort()]);
  }

  target(path) {
    return targetAt(this.draft, path);
  }

  rememberVerifiedVitals() {
    this.verifiedVitalData = new Map();
    for (const [index, vital] of this.draft.vitals.entries()) {
      if (!this.missing.includes(vital.item)
        && !this.checks.some((check) => check.path === `vitals[${index}]` && check.level === "stop")) {
        this.verifiedVitalData.set(index, JSON.stringify(vital));
      }
    }
  }

  action(path) {
    const decision = this.decisions.get(path);
    return decision?.fingerprint === this.fingerprint(path) ? decision.action : null;
  }

  touch(path, { entail = false } = {}) {
    if (this.disposed || this.isLocked()) return;
    this.resetSaveError();
    this.revision += 1;
    this.controller?.abort();
    this.status = "dirty";
    this.error = "";
    this.needsEntail ||= entail;
    this.decisions.delete(path);
    this.multipleConfirmed.delete(path);
    this.editedPaths.add(path);
    this.counts.edited = this.editedPaths.size;
  }

  setVital(index, item, value) {
    if (this.disposed || this.isLocked() || value.length > 100 || !vitalItems.some((vital) => vital.item === item)) return null;
    let position = index;
    if (position === null) {
      if (!value.trim() || this.draft.vitals.length >= 30) return null;
      position = this.draft.vitals.length;
      this.draft.vitals.push({ item, value: "", evidence: [], source: "manual" });
    }
    const vital = this.draft.vitals[position];
    if (!vital || vital.item !== item) return null;
    if (vital.value === value && vital.source === "manual") return position;
    vital.value = value;
    vital.source = "manual";
    vital.evidence = [];
    this.touch(`vitals[${position}]`);
    return position;
  }

  setSoap(part, index, value) {
    if (this.disposed || this.isLocked() || value.length > 5000) return;
    if (["A", "P"].includes(part)) {
      if (this.draft.soap[part] === value) return;
      this.draft.soap[part] = value;
      this.touch(`soap.${part}`);
    } else if (["S", "O"].includes(part) && this.draft.soap[part][index]) {
      this.setElement(`soap.${part}[${index}]`, value);
    }
  }

  addElement(kind) {
    if (this.disposed || this.isLocked()) return null;
    const list = elementList(this.draft, kind);
    if (!list || list.length >= (kind.startsWith("soap.") ? 50 : 30)) return null;
    const item = { text: "", evidence: [], added_by: "nurse", ...(kind === "requests" ? { urgency: "none", cue: null } : {}) };
    list.push(item);
    this.addedElements.add(item);
    const path = `${kind}[${list.length - 1}]`;
    this.touch(path);
    return path;
  }

  setElement(path, value) {
    if (this.disposed || this.isLocked() || typeof value !== "string" || value.length > 5000) return;
    const item = this.target(path);
    if (!item || typeof item.text !== "string" || item.text === value || path.endsWith(".cue")) return;
    const wasAI = item.added_by !== "nurse";
    item.text = value;
    // 元のAI文のコピーを手入力扱いにして照合を飛ばさないようにします。
    if (this.addedElements.has(item)) item.added_by = this.originalAiTexts.has(normalizedText(value)) ? "ai" : "nurse";
    this.touch(path, { entail: wasAI || item.added_by !== "nurse" });
  }

  setRequestUrgency(index, value) {
    if (this.disposed || this.isLocked() || !["said_urgent", "timed", "none"].includes(value)) return;
    const item = this.draft.requests[index];
    if (!item || item.added_by !== "nurse" || item.urgency === value) return;
    item.urgency = value;
    this.touch(`requests[${index}]`);
  }

  setEvidence(path, id, checked) {
    if (this.disposed || this.isLocked()) return false;
    const item = this.target(path);
    if (!this.addedElements.has(item) || !this.utterances.some((utterance) => utterance.id === id)) return false;
    const next = checked ? [...new Set([...item.evidence, id])] : item.evidence.filter((value) => value !== id);
    if (next.length > 3) return false;
    if (JSON.stringify(item.evidence) === JSON.stringify(next)) return true;
    item.evidence = next;
    this.touch(path, { entail: item.added_by !== "nurse" });
    return true;
  }

  removeAdded(path) {
    if (this.disposed || this.isLocked()) return false;
    const match = /^(soap\.S|soap\.O|requests|doctor_questions|manual_needed)\[(\d+)\]$/.exec(path);
    if (!match) return false;
    const list = elementList(this.draft, match[1]), index = Number(match[2]);
    if (!this.addedElements.has(list[index])) return false;
    const entail = list.slice(index).some((item) => item.added_by !== "nurse");
    this.addedElements.delete(list[index]);
    list.splice(index, 1);
    const shifted = (key) => key.startsWith(`${match[1]}[`) && Number(key.split("[")[1].split("]")[0]) >= index;
    this.checks = this.checks.filter((check) => !shifted(check.path));
    this.seals = this.seals.filter((seal) => !shifted(seal.path));
    for (const key of this.decisions.keys()) if (shifted(key)) this.decisions.delete(key);
    this.touch(path, { entail });
    return true;
  }

  hasBlankAdded() {
    return [...this.addedElements].some((item) => !item.text.trim());
  }

  checkLevel(path) {
    if (this.status !== "verified" || this.revision !== this.verifiedRevision) return "pending";
    const checks = this.checks.filter((check) => check.path === path || check.path.startsWith(`${path}.`));
    return checks.some((check) => check.level === "stop") ? "stop" : checks.length ? "warn" : "clear";
  }

  usedEvidenceIds() {
    const ids = new Set();
    const remember = (item, path) => {
      if (this.action(path) === "delete") return;
      for (const id of item.evidence) ids.add(id);
      if (item.cue && this.action(`${path}.cue`) !== "delete") for (const id of item.cue.evidence) ids.add(id);
    };
    this.draft.vitals.forEach((item, index) => { if (item.source === "conversation") remember(item, `vitals[${index}]`); });
    for (const kind of addableKinds) elementList(this.draft, kind).forEach((item, index) => remember(item, `${kind}[${index}]`));
    return ids;
  }

  decide(path, action) {
    if (this.disposed || this.isLocked() || !["keep", "delete"].includes(action)
      || this.status !== "verified" || this.revision !== this.verifiedRevision
      || !this.checks.some((check) => check.path === path && check.level === "stop")) return;
    this.resetSaveError();
    if (this.action(path) === action) this.decisions.delete(path);
    else this.decisions.set(path, { action, fingerprint: this.fingerprint(path) });
  }

  confirmMultiple(path) {
    if (this.disposed || this.isLocked()) return;
    if (this.status !== "verified" || this.revision !== this.verifiedRevision) return;
    if (!this.checks.some((check) => check.path === path && check.code === "multiple_values")) return;
    this.resetSaveError();
    if (this.multipleConfirmed.get(path) === this.fingerprint(path)) this.multipleConfirmed.delete(path);
    else this.multipleConfirmed.set(path, this.fingerprint(path));
  }

  getMissing() {
    const present = new Set();
    for (const [index, vital] of this.draft.vitals.entries()) {
      const path = `vitals[${index}]`;
      if (this.action(path) === "delete" || !vital.value.trim()
        || this.checks.some((check) => check.path === path && check.level === "stop")) continue;
      if (this.verifiedVitalData.get(index) === JSON.stringify(vital)) present.add(vital.item);
      else if (vital.source === "manual") {
        const number = "[+-]?\\d+(?:[.,]\\d+)?";
        const pattern = vital.item === "血圧" ? `^${number}\\s*/\\s*${number}$` : `^${number}$`;
        if (new RegExp(pattern).test(vital.value.trim())) present.add(vital.item);
      }
    }
    return requiredVitals.filter((item) => !present.has(item));
  }

  gate() {
    if (this.disposed) return { ready: false, reasons: ["下書きは破棄されています"] };
    const reasons = [];
    if (this.hasBlankAdded()) reasons.push("追加した項目を入力または削除してください");
    if (this.saveStatus === "saving") reasons.push("保存中です");
    if (this.saveStatus === "uncertain") reasons.push("保存結果が未確認です。再送してください");
    if (this.patientMatch.level !== "ok" && !this.patientConfirmed) reasons.push("患者の確認が必要です");
    if (this.status === "verifying") reasons.push("検証中です");
    else if (this.status === "error") reasons.push("再検証してください");
    else if (this.revision !== this.verifiedRevision) reasons.push("修正内容を再検証してください");
    const undecided = new Set(this.checks.filter((check) => check.level === "stop" && !this.action(check.path))
      .map((check) => check.path));
    if (undecided.size) reasons.push(`残す／消すの選択が${undecided.size}件あります`);
    const multiple = new Set(this.checks.filter((check) => check.code === "multiple_values"
      && this.action(check.path) !== "delete"
      && this.multipleConfirmed.get(check.path) !== this.fingerprint(check.path)).map((check) => check.path));
    if (multiple.size) reasons.push("複数あるバイタルの値を確認してください");
    return { ready: !this.disposed && !reasons.length, reasons };
  }

  recordEvidenceTap() {
    if (this.disposed) return;
    this.counts.evidence_taps = Math.min(100000, this.counts.evidence_taps + 1);
  }

  verificationPayload() {
    if (this.disposed) throw new Error("下書きは破棄されています。");
    return clone({ utterances: this.utterances, draft: this.draft, entail: this.needsEntail });
  }

  async verify() {
    if (this.disposed || this.isLocked() || this.status === "verifying") return false;
    this.resetSaveError();
    if (this.hasBlankAdded()) return false;
    const revision = this.revision;
    const controller = new AbortController();
    this.controller = controller;
    const body = this.verificationPayload();
    const previousEntail = this.checks.filter((check) => check.code.startsWith("entail_"));
    this.status = "verifying";
    this.error = "";
    try {
      const data = await verifyDraft(body, { signal: controller.signal });
      if (this.disposed || controller.signal.aborted || revision !== this.revision) return false;
      if (!validChecks(data.checks, this.draft) || !validMissing(data.missing)
        || !Array.isArray(data.entail_seals)) throw invalid();
      this.checks = clone(body.entail ? data.checks : [...data.checks, ...previousEntail]);
      this.missing = clone(data.missing);
      this.rememberVerifiedVitals();
      if (body.entail) this.seals = clone(data.entail_seals);
      this.needsEntail = false;
      this.verifiedRevision = revision;
      this.status = "verified";
      for (const [path, decision] of this.decisions) {
        if (decision.fingerprint !== this.fingerprint(path)) this.decisions.delete(path);
      }
      return true;
    } catch (error) {
      if (this.disposed || controller.signal.aborted || revision !== this.revision) return false;
      this.status = "error";
      this.error = error.message;
      throw error;
    } finally {
      if (this.controller === controller) this.controller = null;
    }
  }

  confirmationData() {
    if (!this.gate().ready) throw new Error("確認が終わっていません。");
    this.confirmId ??= createConfirmId();
    this.timing.confirmed ??= isoJst();
    return clone({
      confirm_id: this.confirmId,
      patient_id: this.patient.id,
      patient_confirmed: this.patientConfirmed,
      utterances: this.utterances,
      draft: this.draft,
      entail_seals: this.seals,
      draft_token: this.draftToken,
      decisions: [...this.decisions.keys()].filter((path) => this.action(path))
        .map((path) => ({ path, action: this.action(path) })),
      ui_counts: this.counts,
      timing: this.timing,
      ...reportedBy(), // 確定した看護師の自己申告（S-08）
    });
  }

  // 送信済みか不明な間は、内容もIDも変えず、同じスナップショットを再送します。
  confirm() {
    if (this.disposed) return Promise.reject(new Error("下書きは破棄されています。"));
    if (this.savePromise) return this.savePromise;
    if (!this.canRetrySave()) {
      if (!this.gate().ready) return Promise.reject(new Error("確認が終わっていません。"));
      this.pendingConfirmation = this.confirmationData();
    }
    this.saveStatus = "saving";
    this.saveError = "";
    const promise = this.sendConfirmation();
    this.savePromise = promise;
    return promise;
  }

  async sendConfirmation() {
    const controller = new AbortController();
    this.saveController = controller;
    try {
      const data = await postRecord(this.pendingConfirmation, { signal: controller.signal });
      if (this.disposed) return null;
      if (data.record_id !== `r_${this.patient.id}_${this.confirmId}`) {
        throw new ApiError("保存した記録を照合できませんでした。", { code: "invalid_confirmation_response" });
      }
      // 応答に余分な欄があっても、会話全文などを出力画面へ持ち越しません。
      const result = {
        mode: data.mode,
        record_id: data.record_id,
        chart_text: data.chart_text,
        tasks_created: [...data.tasks_created],
      };
      this.dispose();
      this.saveStatus = "saved";
      return result;
    } catch (error) {
      if (this.disposed) return null;
      this.saveError = error.message;
      if (!error.status || error.status >= 500 || error.status === 408) {
        // 通信切断・タイムアウト・不正な応答・5xxでは、保存済みの可能性があります。
        this.saveStatus = "uncertain";
      } else {
        // サーバーが明示的に拒否した場合は、編集と確認をやり直せます。
        this.saveStatus = "error";
        this.pendingConfirmation = null;
        this.timing.confirmed = null;
        if (error.status === 409 && error.code === "patient_not_confirmed") {
          this.patientConfirmed = false;
          if (this.patientMatch.level === "ok") this.patientMatch.level = "confirm";
          this.patientMatch.reasons = [error.message];
        } else if (error.status === 409) {
          this.status = "dirty";
          this.verifiedRevision = -1;
          this.needsEntail = true;
          this.decisions.clear();
        }
      }
      throw error;
    } finally {
      if (this.saveController === controller) this.saveController = null;
      this.savePromise = null;
    }
  }

  dispose() {
    if (this.disposed) return;
    this.controller?.abort();
    this.saveController?.abort();
    if (this.audioUrl) URL.revokeObjectURL(this.audioUrl);
    this.audioUrl = null;
    this.audio = null;
    this.utterances = [];
    this.draft = null;
    this.addedElements.clear();
    this.originalAiTexts.clear();
    this.checks = [];
    this.seals = [];
    this.draftToken = null;
    this.patient = null;
    this.patientMatch = null;
    this.missing = [];
    this.verifiedVitalData.clear();
    this.editedPaths.clear();
    this.decisions.clear();
    this.multipleConfirmed.clear();
    this.pendingConfirmation = null;
    this.confirmId = null;
    this.timing = null;
    this.saveError = "";
    this.disposed = true;
  }
}
