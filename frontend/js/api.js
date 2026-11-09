import { clearPasscode, getPasscode } from "./auth.js";

export const MODE_EVENT = "nursenote:api-mode";
export const AUTH_REQUIRED_EVENT = "nursenote:auth-required";

const messages = {
  400: "送信内容をご確認ください。",
  401: "合言葉が違います。",
  403: "この操作は許可されていません。",
  404: "対象のデータが見つかりません。",
  409: "確認が必要な項目があります。",
  413: "データが大きすぎます。",
  422: "入力内容をご確認ください。",
  429: "本日の利用上限に達しました。",
  500: "処理に失敗しました。時間をおいてお試しください。",
  502: "AI処理または文字起こしに失敗しました。",
};

export class ApiError extends Error {
  constructor(message, { status = 0, code = "request_failed" } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function reportMode(mode) {
  if (mode === "mock" || mode === "live") {
    window.dispatchEvent(new CustomEvent(MODE_EVENT, { detail: { mode } }));
  }
}

function handleUnauthorized(passcode, error) {
  // 古い通信の401で、新しく入力し直した合言葉を削除しないようにします。
  const current = getPasscode();
  if (current && current !== passcode) return;
  clearPasscode();
  window.dispatchEvent(new CustomEvent(AUTH_REQUIRED_EVENT, {
    detail: { message: error.message },
  }));
}

/** 同じオリジンの /api/ のみへ送信します。書き込みも含め、自動再送はしません。 */
export async function request(path, {
  method = "GET",
  body,
  signal,
  authenticated = true,
  passcode = getPasscode(),
  timeoutMs = 30000,
} = {}) {
  const url = new URL(path, window.location.origin);
  if (url.origin !== window.location.origin || !url.pathname.startsWith("/api/")) {
    throw new ApiError("接続先が正しくありません。", { code: "invalid_endpoint" });
  }

  if (authenticated && !passcode) {
    const error = new ApiError("合言葉を入力してください。", {
      status: 401, code: "bad_passcode",
    });
    handleUnauthorized(passcode, error);
    throw error;
  }

  const headers = new Headers({ Accept: "application/json" });
  if (authenticated) headers.set("X-Passcode", passcode);

  let payload = body;
  if (body !== undefined && !(body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
    payload = JSON.stringify(body);
  }

  const controller = new AbortController();
  let timedOut = false;
  const abort = () => controller.abort();
  if (signal?.aborted) abort();
  else signal?.addEventListener("abort", abort, { once: true });
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  try {
    const response = await fetch(url, {
      method,
      headers,
      body: payload,
      signal: controller.signal,
      cache: "no-store",
      credentials: "omit",
      redirect: "error",
    });

    let data;
    try {
      data = await response.json();
    } catch (error) {
      if (controller.signal.aborted) throw error;
      // JSONではないHTTPエラーも、状態コードに応じて扱います。
      if (response.ok) {
        throw new ApiError("応答を読み取れませんでした。", { code: "invalid_response" });
      }
    }

    // エラー応答にもmodeがあるため、成功・失敗の両方から更新します。
    reportMode(data?.mode);

    if (!response.ok) {
      const message = typeof data?.error?.message === "string" && data.error.message
        ? data.error.message
        : messages[response.status] ?? "通信に失敗しました。";
      const code = typeof data?.error?.code === "string"
        ? data.error.code
        : "http_error";
      const error = new ApiError(message, { status: response.status, code });
      if (response.status === 401 && authenticated) handleUnauthorized(passcode, error);
      throw error;
    }

    if (data?.mode !== "mock" && data?.mode !== "live") {
      throw new ApiError("応答の形式が正しくありません。", { code: "invalid_response" });
    }
    return data;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (timedOut) {
      throw new ApiError("応答に時間がかかっています。もう一度お試しください。", {
        code: "timeout",
      });
    }
    if (controller.signal.aborted) {
      throw new ApiError("通信を中止しました。", { code: "aborted" });
    }
    throw new ApiError("接続できません。通信環境をご確認ください。", { code: "network_error" });
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", abort);
  }
}

export async function getHealth(options = {}) {
  const data = await request("/api/health", { ...options, authenticated: false, timeoutMs: 8000 });
  if (data.status !== "ok") {
    throw new ApiError("接続を確認できませんでした。", { code: "invalid_response" });
  }
  return data;
}

export async function getPatients(options = {}) {
  const data = await request("/api/patients", { ...options, timeoutMs: 10000 });
  if (!Array.isArray(data.patients)) {
    throw new ApiError("患者一覧を読み取れませんでした。", { code: "invalid_response" });
  }
  return data;
}

export async function getOpenTasks(options = {}) {
  const data = await request("/api/tasks?status=open", { ...options, timeoutMs: 10000 });
  if (!Array.isArray(data.tasks)) {
    throw new ApiError("タスクを読み取れませんでした。", { code: "invalid_response" });
  }
  return data;
}

export async function getAllTasks(options = {}) {
  const data = await request("/api/tasks?status=all", { ...options, timeoutMs: 10000 });
  if (!Array.isArray(data.tasks)) {
    throw new ApiError("タスクを読み取れませんでした。", { code: "invalid_response" });
  }
  return data;
}

export async function patchTask(id, changes, options = {}) {
  const data = await request(`/api/tasks/${encodeURIComponent(id)}`, {
    ...options, method: "PATCH", body: changes,
  });
  if (!data.task || data.task.id !== id) {
    throw new ApiError("タスクの更新結果を読み取れませんでした。", { code: "invalid_response" });
  }
  return data;
}

export function createDraft(body, options = {}) {
  return request("/api/drafts", { ...options, method: "POST", body, timeoutMs: 180000 });
}

export function verifyDraft(body, options = {}) {
  return request("/api/verify", { ...options, method: "POST", body, timeoutMs: 180000 });
}

export async function postRecord(body, options = {}) {
  const data = await request("/api/records", { ...options, method: "POST", body, timeoutMs: 180000 });
  if (typeof data.record_id !== "string" || typeof data.chart_text !== "string" || !data.chart_text.trim()
    || !Array.isArray(data.tasks_created) || data.tasks_created.some((id) => typeof id !== "string")) {
    throw new ApiError("保存結果を読み取れませんでした。", { code: "invalid_confirmation_response" });
  }
  return data;
}

export async function getRecords({ patientId = "", ...options } = {}) {
  const query = patientId ? `?patient_id=${encodeURIComponent(patientId)}` : "";
  const data = await request(`/api/records${query}`, { ...options, timeoutMs: 10000 });
  if (!Array.isArray(data.records)) {
    throw new ApiError("記録一覧を読み取れませんでした。", { code: "invalid_response" });
  }
  return data;
}

export async function getRecord(recordId, options = {}) {
  if (typeof recordId !== "string" || !/^r_[A-Za-z0-9_-]{1,90}$/.test(recordId)) {
    throw new ApiError("記録の指定が正しくありません。", { code: "invalid_record_id" });
  }
  const data = await request(`/api/records/${encodeURIComponent(recordId)}`, { ...options, timeoutMs: 10000 });
  if (!data.record || data.record.record_id !== recordId) {
    throw new ApiError("記録の詳細を読み取れませんでした。", { code: "invalid_response" });
  }
  return data;
}
