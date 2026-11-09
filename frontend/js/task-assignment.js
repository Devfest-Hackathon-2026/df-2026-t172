// 担当者の変更は画面内だけのデモです。個人の認証やDBの担当者とは連携しません。
export const DEMO_TASK_ASSIGNEES = Object.freeze([
  Object.freeze({ value: "", label: "未割り振り", shortLabel: "未割り振り" }),
  Object.freeze({ value: "self", label: "自分で取る", shortLabel: "自分" }),
  Object.freeze({ value: "nurse_a", label: "看護師Aに回す（架空）", shortLabel: "看護師A" }),
  Object.freeze({ value: "nurse_b", label: "看護師Bに回す（架空）", shortLabel: "看護師B" }),
  Object.freeze({ value: "nurse_c", label: "看護師Cに回す（架空）", shortLabel: "看護師C" }),
]);

export const TASK_ASSIGNMENT_NOTE = "担当の変更はお試し用です。再読み込みするとリセットされます。";
