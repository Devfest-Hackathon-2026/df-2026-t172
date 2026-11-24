import { ApiError } from "./api.js?v=20261121-context-help";

const idPattern = /^[A-Za-z0-9_-]{1,40}$/u;
const invalid = () => new ApiError("看護計画の形式が正しくありません。", { code: "invalid_response" });

export function normalizePlanId(value) {
  if (value == null) return null;
  if (typeof value !== "string" || !idPattern.test(value)) throw invalid();
  return value;
}

export function normalizeCarePlans(value) {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.length > 10) throw invalid();
  const ids = new Set(), labels = new Set();
  return value.map((plan) => {
    if (!plan || normalizePlanId(plan.id) === null || typeof plan.label !== "string"
      || !plan.label.trim() || [...plan.label].length > 100 || /[\r\n]/u.test(plan.label)
      || plan.label !== plan.label.trim() || plan.label.normalize("NFKC") === "計画外"
      || ids.has(plan.id) || labels.has(plan.label.normalize("NFKC"))) throw invalid();
    ids.add(plan.id); labels.add(plan.label.normalize("NFKC"));
    return { id: plan.id, label: plan.label };
  });
}

/** 表示用の参照だけを作る。照合が指す元の配列と番号は動かさない。 */
export function groupSoapByPlan(soap, carePlans) {
  const groups = [...carePlans.map((plan) => ({ ...plan, entries: [] })), { id: null, label: "計画外", entries: [] }];
  for (const part of ["S", "O"]) {
    soap[part].forEach((item, index) => {
      const group = groups.find((g) => g.id === (item.plan_id ?? null));
      if (!group) throw invalid();
      group.entries.push({ part, index, path: `soap.${part}[${index}]`, item });
    });
  }
  return groups;
}
