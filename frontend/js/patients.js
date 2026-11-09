import { ApiError, getPatients } from "./api.js";

const roomOrder = new Intl.Collator("ja", { numeric: true });

export function displayName(patient) {
  return typeof patient?.full_name === "string" && patient.full_name.trim() ? patient.full_name : patient?.name ?? "";
}

export function sortPatients(patients) {
  return [...patients].sort((a, b) => roomOrder.compare(a.room, b.room)
    || roomOrder.compare(a.bed, b.bed)
    || roomOrder.compare(a.name, b.name));
}

export async function loadPatients(options = {}) {
  const { patients } = await getPatients(options);
  if (patients.some((patient) => !patient || ["id", "room", "bed", "name"]
    .some((key) => typeof patient[key] !== "string")
    || ["full_name", "full_kana"].some((key) => patient[key] !== undefined && typeof patient[key] !== "string"))) {
    throw new ApiError("患者一覧を読み取れませんでした。", { code: "invalid_response" });
  }
  return sortPatients(patients);
}
