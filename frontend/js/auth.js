const PASSCODE_KEY = "nursenote.passcode";

export function getPasscode() {
  try {
    return window.sessionStorage.getItem(PASSCODE_KEY) || null;
  } catch {
    return null;
  }
}

export function setPasscode(passcode) {
  try {
    window.sessionStorage.setItem(PASSCODE_KEY, passcode);
  } catch {
    throw new Error("合言葉を保持できません。ブラウザの設定をご確認ください。");
  }
}

export function clearPasscode() {
  try {
    window.sessionStorage.removeItem(PASSCODE_KEY);
  } catch {
    // 保存先を利用できない場合も、入力画面への移動は妨げません。
  }
}

export function renderAuth({ onSubmit, message = "", pending = false, onRetry } = {}) {
  const view = document.createElement("section");
  view.className = "auth-screen";
  const form = document.createElement("form");
  form.className = "auth-form";
  const title = document.createElement("h1");
  title.className = "auth-title";
  title.id = "auth-title";
  title.textContent = onRetry ? "接続を確認" : "合言葉";
  form.setAttribute("aria-labelledby", title.id);

  const errorMessage = document.createElement("p");
  errorMessage.className = "form-error";
  errorMessage.id = "auth-error";
  errorMessage.setAttribute("role", "alert");
  errorMessage.textContent = message;
  errorMessage.hidden = !message;

  const button = document.createElement("button");
  button.type = "submit";
  button.className = "primary-button";

  let input;
  if (!onRetry) {
    input = document.createElement("input");
    input.className = "input";
    input.type = "password";
    input.name = "passcode";
    input.autocomplete = "current-password";
    input.autocapitalize = "none";
    input.spellcheck = false;
    input.required = true;
    input.setAttribute("aria-labelledby", title.id);
    input.setAttribute("aria-describedby", errorMessage.id);
    input.addEventListener("input", () => {
      input.removeAttribute("aria-invalid");
      errorMessage.hidden = true;
      button.disabled = !input.value.trim();
    });
  }

  function setPending(busy) {
    form.setAttribute("aria-busy", String(busy));
    if (input) input.disabled = busy;
    button.disabled = busy || Boolean(input && !input.value.trim());
    button.textContent = busy ? "確認中…" : onRetry ? "再試行" : "開く";
  }

  form.append(title);
  if (input) form.append(input);
  form.append(errorMessage, button);
  setPending(pending);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (form.getAttribute("aria-busy") === "true" || (input && !input.value.trim())) return;
    setPending(true);
    errorMessage.hidden = true;
    try {
      if (onRetry) await onRetry();
      else await onSubmit(input.value);
      if (input) input.value = "";
    } catch (error) {
      errorMessage.textContent = error.message || "接続できませんでした。";
      errorMessage.hidden = false;
      if (input && error.status === 401) {
        input.value = "";
        input.setAttribute("aria-invalid", "true");
      }
    } finally {
      setPending(false);
    }
  });

  view.append(form);
  return view;
}
