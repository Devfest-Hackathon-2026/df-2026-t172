export const MAX_AUDIO_SECONDS = 180;
export const MAX_AUDIO_BYTES = 10 * 1024 * 1024;
// タイマーの遅れでサーバーの3分上限を越えないよう、通常は1秒手前で止めます。
const STOP_AT_SECONDS = MAX_AUDIO_SECONDS - 1;

const mimeTypes = ["audio/mp4;codecs=mp4a.40.2", "audio/mp4", "audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"];

export class RecordingError extends Error {
  constructor(message, code = "recording_failed") {
    super(message);
    this.name = "RecordingError";
    this.code = code;
  }
}

export function audioFilename(type) {
  const format = (type || "").toLowerCase().split(";")[0];
  const extension = { "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/webm": "webm", "audio/ogg": "ogg", "audio/wav": "wav" }[format] ?? "bin";
  return `recording.${extension}`;
}

export function selectAudioType(Recorder) {
  if (typeof Recorder.isTypeSupported !== "function") return "";
  return mimeTypes.find((type) => Recorder.isTypeSupported(type)) ?? "";
}

function microphoneError(error) {
  if (error instanceof RecordingError) return error;
  const messages = {
    NotAllowedError: "マイクの使用が許可されていません。ブラウザの設定で許可してください。",
    SecurityError: "マイクを使用できません。ブラウザの設定をご確認ください。",
    NotFoundError: "マイクが見つかりません。",
    NotReadableError: "マイクを使用できません。ほかのアプリで使用していないかご確認ください。",
    NotSupportedError: "この環境では録音できません。Safari か Chrome で開いてください。",
  };
  return new RecordingError(messages[error?.name] ?? "録音できませんでした。もう一度お試しください。", error?.name ?? "recording_failed");
}

/** 音声はこのインスタンスのメモリだけに保持し、破棄後の遅い許可・イベントも無視します。 */
export class AudioRecorder {
  constructor({ onTick = () => {}, onStopped = () => {}, onError = () => {}, environment = {} } = {}) {
    this.env = {
      mediaDevices: globalThis.navigator?.mediaDevices,
      Recorder: globalThis.MediaRecorder,
      secure: globalThis.isSecureContext,
      now: () => performance.now(), wallNow: () => new Date(),
      setInterval: (callback, ms) => globalThis.setInterval(callback, ms),
      clearInterval: (timer) => globalThis.clearInterval(timer),
      setTimeout: (callback, ms) => globalThis.setTimeout(callback, ms),
      clearTimeout: (timer) => globalThis.clearTimeout(timer),
      ...environment,
    };
    this.onTick = onTick;
    this.onStopped = onStopped;
    this.onError = onError;
    this.status = "idle";
    this.result = null;
    this.stream = null;
    this.recorder = null;
    this.chunks = [];
    this.size = 0;
    this.elapsed = 0;
    this.startedAt = null;
    this.stoppedAt = null;
    this.startedClock = null;
    this.timer = null;
    this.stopTimer = null;
    this.trackListeners = [];
    this.disposed = false;
    this.stopReason = null;
    this.finished = null;
    this.resolveFinished = null;
  }

  duration() {
    return this.status === "recording" ? Math.max(0, (this.env.now() - this.startedClock) / 1000) : this.elapsed;
  }

  async start({ consentConfirmed = false } = {}) {
    if (this.disposed || this.status !== "idle") return false;
    if (!consentConfirmed) throw new RecordingError("録音の前に患者さんの同意を確かめてください。", "consent_required");
    if (this.env.secure === false) throw new RecordingError("録音にはHTTPSで開いてください。", "insecure_context");
    if (!this.env.mediaDevices?.getUserMedia || typeof this.env.Recorder !== "function") {
      throw new RecordingError("このブラウザでは録音できません。Safari か Chrome で開いてください。", "recording_unavailable");
    }
    this.status = "requesting";
    try {
      const stream = await this.env.mediaDevices.getUserMedia({ audio: true, video: false });
      if (this.disposed) {
        stream.getTracks().forEach((track) => track.stop());
        return false;
      }
      this.stream = stream;
      if (!stream.getAudioTracks().some((track) => track.readyState === "live")) {
        throw new RecordingError("マイクから音声を取得できませんでした。", "microphone_unavailable");
      }
      const mimeType = selectAudioType(this.env.Recorder);
      const recorder = new this.env.Recorder(stream, { ...(mimeType ? { mimeType } : {}), audioBitsPerSecond: 64000 });
      this.recorder = recorder;
      this.finished = new Promise((resolve) => { this.resolveFinished = resolve; });
      recorder.ondataavailable = (event) => {
        if (this.disposed || ["error", "stopped"].includes(this.status) || !event.data?.size) return;
        this.size += event.data.size;
        if (this.size > MAX_AUDIO_BYTES) {
          this.fail(new RecordingError("録音が10MBを超えました。短く録り直してください。", "audio_too_large"));
          return;
        }
        this.chunks.push(event.data);
      };
      recorder.onstop = () => this.finish();
      recorder.onerror = () => this.fail(new RecordingError("録音が中断されました。もう一度録音してください。"));
      recorder.onpause = () => this.stop("interrupted");
      for (const track of stream.getAudioTracks()) {
        const listener = () => this.stop("interrupted");
        track.addEventListener("ended", listener);
        this.trackListeners.push([track, listener]);
      }
      recorder.start(1000);
      this.startedClock = this.env.now();
      this.startedAt = this.env.wallNow();
      this.status = "recording";
      this.timer = this.env.setInterval(() => {
        if (this.duration() >= STOP_AT_SECONDS) this.stop("limit");
        else this.onTick();
      }, 250);
      this.onTick();
      return true;
    } catch (error) {
      if (this.disposed) return false;
      this.status = "error";
      this.releaseMedia();
      this.chunks = [];
      this.resolveFinished?.(null);
      throw microphoneError(error);
    }
  }

  stop(reason = "manual") {
    if (this.disposed || !["recording", "stopping"].includes(this.status)) return Promise.resolve(this.result);
    if (this.status === "stopping") return this.finished;
    this.elapsed = this.duration();
    this.stoppedAt = this.env.wallNow();
    this.stopReason = reason;
    this.status = "stopping";
    this.stopTimer = this.env.setTimeout(() => this.fail(new RecordingError("録音の終了を確認できませんでした。録り直してください。")), 10000);
    try {
      if (this.recorder.state !== "inactive") this.recorder.stop();
      else this.finish();
    } catch {
      this.fail(new RecordingError("録音を停止できませんでした。もう一度録音してください。"));
    }
    this.releaseMedia();
    this.onTick();
    return this.finished;
  }

  finish() {
    if (this.disposed || ["error", "stopped"].includes(this.status)) return;
    this.clearStopTimer();
    // OSによる停止でも、終了した時刻を残してマイクを解放します。
    if (this.status !== "stopping") {
      this.elapsed = this.duration();
      this.stoppedAt = this.env.wallNow();
      this.stopReason = "interrupted";
    }
    this.releaseMedia();
    const type = this.recorder?.mimeType || this.chunks.find((chunk) => chunk.type)?.type || "";
    const audio = new Blob(this.chunks, { type });
    this.chunks = [];
    if (!audio.size || this.elapsed <= 0 || this.elapsed > MAX_AUDIO_SECONDS) {
      this.fail(new RecordingError(this.elapsed > MAX_AUDIO_SECONDS
        ? "録音が3分を超えました。短く録り直してください。" : "音声を取得できませんでした。もう一度録音してください。", "invalid_recording"));
      return;
    }
    this.status = "stopped";
    this.result = { audio, durationSeconds: this.elapsed, startedAt: this.startedAt, stoppedAt: this.stoppedAt, reason: this.stopReason };
    this.resolveFinished?.(this.result);
    this.resolveFinished = null;
    this.onStopped(this.result);
  }

  fail(error) {
    if (this.disposed || this.status === "error") return;
    this.status = "error";
    this.clearStopTimer();
    this.releaseMedia();
    this.chunks = [];
    this.result = null;
    this.resolveFinished?.(null);
    this.resolveFinished = null;
    this.onError(error);
  }

  releaseMedia() {
    if (this.timer !== null) this.env.clearInterval(this.timer);
    this.timer = null;
    for (const [track, listener] of this.trackListeners) track.removeEventListener("ended", listener);
    this.trackListeners = [];
    if (this.recorder?.state !== "inactive") {
      try { this.recorder?.stop(); } catch { /* 解放を続けます。 */ }
    }
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
  }

  clearStopTimer() {
    if (this.stopTimer !== null) this.env.clearTimeout(this.stopTimer);
    this.stopTimer = null;
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    this.clearStopTimer();
    this.releaseMedia();
    if (this.recorder) {
      this.recorder.ondataavailable = null;
      this.recorder.onstop = null;
      this.recorder.onerror = null;
      this.recorder.onpause = null;
    }
    this.recorder = null;
    this.result = null;
    this.chunks = [];
    this.size = 0;
    this.startedAt = null;
    this.stoppedAt = null;
    this.resolveFinished?.(null);
    this.resolveFinished = null;
    this.finished = null;
    this.onTick = this.onStopped = this.onError = () => {};
    this.status = "disposed";
  }
}
