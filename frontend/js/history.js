import { ApiError, getRecord, getRecords } from "./api.js";
import { ensureNurses } from "./assignment.js";

const text = (value) => typeof value === "string";
const id = (value) => text(value) && /^[A-Za-z0-9_-]{1,40}$/.test(value);
const recordId = (value) => text(value) && /^r_[A-Za-z0-9_-]{1,90}$/.test(value);
const date = (value) => text(value) && Number.isFinite(Date.parse(value));
const strings = (value) => Array.isArray(value) && value.every(text);
const evidence = (value) => strings(value) && value.length <= 3;
const items = (value, validate) => Array.isArray(value) && value.every(validate);
const origin = (value) => value === undefined || ["ai", "nurse"].includes(value);
const sentence = (value) => value && text(value.text) && evidence(value.evidence) && origin(value.added_by);
const cue = (value) => value === null || (sentence(value) && ["時間指定", "患者が急ぎと言った"].includes(value.kind));
const invalid = () => new ApiError("記録を読み取れませんでした。", { code: "invalid_response" });

function summary(value) {
  return value && recordId(value.record_id) && id(value.patient_id)
    && value.record_id.startsWith(`r_${value.patient_id}_`)
    && text(value.room) && text(value.name) && date(value.created_at)
    && (value.full_name === undefined || text(value.full_name))
    && (value.s_preview === null || text(value.s_preview))
    && (value.o_preview === null || text(value.o_preview))
    && Number.isInteger(value.request_count) && value.request_count >= 0;
}

/** 一覧も詳細もAPIの期限切れ除外に従い、日付を変えた検索や端末への保存は行いません。 */
export async function loadRecords(options = {}) {
  const { records } = await getRecords(options);
  if (records.some((record) => !summary(record)
    || (options.patientId && record.patient_id !== options.patientId))
    || new Set(records.map((record) => record.record_id)).size !== records.length) throw invalid();
  return records.map(({ record_id, patient_id, room, name, full_name, created_at, s_preview, o_preview, request_count }) => ({
    record_id, patient_id, room, name, full_name: typeof full_name === "string" ? full_name : "", created_at, s_preview, o_preview, request_count,
  })).sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
}

export async function loadRecord(requestedId, options = {}) {
  // 確定した人（自己申告）を名前で出すため、看護師の一覧も読みます（読めなければ id のまま出します）
  const { record } = await getRecord(requestedId, options);
  await ensureNurses(options); if (!id(record.patient_id) || !record.record_id.startsWith(`r_${record.patient_id}_`)
    || !text(record.room) || !text(record.name) || !date(record.created_at)
    || (record.full_name !== undefined && !text(record.full_name))
    || !text(record.chart_text) || !record.chart_text.trim()
    || !items(record.vitals, (v) => v && text(v.item) && text(v.value) && evidence(v.evidence)
      && ["conversation", "manual"].includes(v.source))
    || !record.soap || !items(record.soap.S, sentence) || !items(record.soap.O, sentence)
    || !text(record.soap.A) || !text(record.soap.P)
    || !items(record.requests, (r) => sentence(r) && ["said_urgent", "timed", "none"].includes(r.urgency) && cue(r.cue))
    || !items(record.manual_needed, sentence) || !items(record.doctor_questions, sentence)
    || !items(record.evidence_utterances, (u) => u && text(u.id) && text(u.text)
      && ["nurse", "patient", "unknown"].includes(u.speaker))
    || new Set(record.evidence_utterances.map((u) => u.id)).size !== record.evidence_utterances.length
    || !items(record.kept_after_check, (check) => check && text(check.path) && strings(check.codes) && text(check.note))
    || !record.patient_check || !["ok", "confirm", "stop"].includes(record.patient_check.level)
    || typeof record.patient_check.confirmed_by_nurse !== "boolean"
    || !(record.patient_check.note === null || text(record.patient_check.note))
    || !(record.confirmed_reported_by == null || id(record.confirmed_reported_by))) throw invalid();

  // 応答に余分な欄があっても、音声や会話全文を履歴の状態に持ち込みません。
  const copySentence = ({ text, evidence, added_by }) => ({ text, evidence: [...evidence], added_by: added_by ?? "ai" });
  return {
    record_id: record.record_id, patient_id: record.patient_id, room: record.room, name: record.name,
    full_name: typeof record.full_name === "string" ? record.full_name : "",
    created_at: record.created_at, chart_text: record.chart_text,
    vitals: record.vitals.map(({ item, value, source, evidence }) => ({ item, value, source, evidence: [...evidence] })),
    soap: { S: record.soap.S.map(copySentence), O: record.soap.O.map(copySentence), A: record.soap.A, P: record.soap.P },
    requests: record.requests.map((r) => ({
      ...copySentence(r), urgency: r.urgency,
      cue: r.cue ? { kind: r.cue.kind, text: r.cue.text, evidence: [...r.cue.evidence] } : null
    })),
    manual_needed: record.manual_needed.map(copySentence), doctor_questions: record.doctor_questions.map(copySentence),
    evidence_utterances: record.evidence_utterances.map(({ id, speaker, text }) => ({ id, speaker, text })),
    kept_after_check: record.kept_after_check.map(({ path, codes, note }) => ({ path, codes: [...codes], note })),
    patient_check: {
      level: record.patient_check.level, confirmed_by_nurse: record.patient_check.confirmed_by_nurse,
      note: record.patient_check.note
    },
    // 確定した看護師の自己申告（S-08）。前からある記録にはないので null にします
    confirmed_reported_by: record.confirmed_reported_by ?? null,
  };
}

const timeFormat = new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
export function recordTime(value) {
  return timeFormat.format(new Date(value));
}

export function savedTarget(record, path) {
  const match = /^(vitals|soap\.S|soap\.O|requests|manual_needed|doctor_questions)\[(\d+)\](\.cue)?$/.exec(path);
  if (!match || (match[3] && match[1] !== "requests")) return "";
  const list = match[1].startsWith("soap.") ? record.soap[match[1].slice(-1)] : record[match[1]];
  const value = match[3] ? list[Number(match[2])]?.cue : list[Number(match[2])];
  return value ? match[1] === "vitals" ? `${value.item} ${value.value}` : value.text : "";
}
