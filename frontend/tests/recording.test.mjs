import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { afterEach, beforeEach, test } from "node:test";
import { AudioRecorder, audioFilename, MAX_AUDIO_BYTES, selectAudioType } from "../js/recorder.js";
import { createAudioReview } from "../js/records.js";
import { clearPatientData, confirmConsent, getState, openTextInput, selectPatient, setDraftPhase, setFirstSpeaker, setRecorder, setReview } from "../js/state.js";

const fixture = JSON.parse(await readFile(new URL("../../backend/mock/draft_s1.json", import.meta.url), "utf8"));
const originalFetch = globalThis.fetch;
const result = () => ({ audio: new Blob(["test-only-audio"], { type: "audio/mp4" }), durationSeconds: 2.5,
  startedAt: new Date("2026-11-08T00:00:00Z"), stoppedAt: new Date("2026-11-08T00:00:02.500Z") });

function microphone({ supported = ["audio/mp4"], bytes = "test-audio", failure, recorderFailure } = {}) {
  const track = new EventTarget();
  Object.assign(track, { readyState: "live", stops: 0, stop() { this.readyState = "ended"; this.stops += 1; } });
  const stream = { getTracks: () => [track], getAudioTracks: () => [track] };
  let clock = 0, tick, requests = 0, instance;
  class Recorder {
    static isTypeSupported(type) { return supported.includes(type); }
    constructor(givenStream, options) {
      if (recorderFailure === "constructor") throw new Error("unsupported");
      assert.equal(givenStream, stream);
      this.options = options;
      this.mimeType = options.mimeType || "audio/webm";
      this.state = "inactive";
      this.stops = 0;
      instance = this;
    }
    start(slice) {
      if (recorderFailure === "start") throw new Error("start failed");
      assert.equal(slice, 1000);
      this.state = "recording";
    }
    stop() {
      this.stops += 1;
      this.state = "inactive";
      queueMicrotask(() => {
        this.ondataavailable?.({ data: new Blob([bytes], { type: this.mimeType }) });
        this.onstop?.();
      });
    }
  }
  return { track, stream, Recorder,
    get instance() { return instance; }, get requests() { return requests; },
    advance(seconds) { clock += seconds * 1000; tick?.(); },
    environment: { secure: true, Recorder, mediaDevices: { async getUserMedia(constraints) {
      requests += 1;
      assert.deepEqual(constraints, { audio: true, video: false });
      if (failure) throw new DOMException("test", failure);
      return stream;
    } }, now: () => clock, wallNow: () => new Date(Date.parse("2026-11-08T00:00:00Z") + clock),
    setInterval(callback) { tick = callback; return 1; }, clearInterval() { tick = null; } },
  };
}

beforeEach(() => {
  globalThis.window = Object.assign(new EventTarget(), { location: { origin: "http://localhost:8765" },
    sessionStorage: { getItem: () => "test-only-passcode", removeItem() {} } });
  clearPatientData();
});
afterEach(() => { clearPatientData(); globalThis.fetch = originalFetch; delete globalThis.window; });

test("microphone access requires consent, a secure context and supported browser APIs", async () => {
  const mic = microphone();
  await assert.rejects(new AudioRecorder({ environment: mic.environment }).start(), { code: "consent_required" });
  await assert.rejects(new AudioRecorder({ environment: { ...mic.environment, secure: false } }).start({ consentConfirmed: true }), { code: "insecure_context" });
  for (const missingApi of [{ Recorder: undefined }, { mediaDevices: undefined }]) {
    await assert.rejects(new AudioRecorder({ environment: { ...mic.environment, ...missingApi } }).start({ consentConfirmed: true }),
      { code: "recording_unavailable", message: "このブラウザでは録音できません。Safari か Chrome で開いてください。" });
  }
  assert.equal(mic.requests, 0);
});

test("unsupported recording and denied permission give different recovery guidance", async () => {
  for (const [failure, pattern] of [["NotSupportedError", /Safari か Chrome/], ["NotAllowedError", /設定で許可/]]) {
    const mic = microphone({ failure });
    await assert.rejects(new AudioRecorder({ environment: mic.environment }).start({ consentConfirmed: true }),
      (error) => error.code === failure && pattern.test(error.message));
  }
});

test("switching from a recording error to text preserves the patient and first speaker while releasing audio", async () => {
  const mic = microphone();
  const recorder = new AudioRecorder({ environment: mic.environment });
  selectPatient(fixture.patient);
  setFirstSpeaker("patient");
  confirmConsent();
  setRecorder(recorder);
  await recorder.start({ consentConfirmed: true });
  setDraftPhase("recording-error", "録音できませんでした", "recording_failed");
  assert.equal(getState().draftErrorCode, "recording_failed");

  openTextInput();
  const state = getState();
  assert.equal(state.phase, "text-input");
  assert.equal(state.inputMethod, "text");
  assert.equal(state.selectedPatient.id, fixture.patient.id);
  assert.equal(state.firstSpeaker, "patient");
  assert.equal(state.recorder, null);
  assert.equal(recorder.disposed, true);
  assert.equal(mic.track.readyState, "ended");
  assert.equal(state.draftError, "");
  assert.equal(state.draftErrorCode, "");
});

test("supported MP4 and WebM types are chosen by capability; names match their actual container", () => {
  assert.equal(selectAudioType(microphone().Recorder), "audio/mp4");
  assert.equal(selectAudioType(microphone({ supported: ["audio/webm;codecs=opus"] }).Recorder), "audio/webm;codecs=opus");
  assert.equal(selectAudioType(class {}), "");
  assert.equal(audioFilename("audio/mp4;codecs=mp4a.40.2"), "recording.m4a");
  assert.equal(audioFilename("audio/webm;codecs=opus"), "recording.webm");
});

test("stop waits for final chunks, uses real elapsed time, releases the mic immediately and runs once", async () => {
  const mic = microphone(); let stopped = 0;
  const recorder = new AudioRecorder({ environment: mic.environment, onStopped() { stopped += 1; } });
  await recorder.start({ consentConfirmed: true });
  mic.advance(2.5);
  const pending = recorder.stop();
  assert.equal(recorder.stop(), pending);
  assert.equal(mic.track.readyState, "ended");
  const recorded = await pending;
  assert.equal(recorded.durationSeconds, 2.5);
  assert.equal(recorded.audio.type, "audio/mp4");
  assert.equal(await recorded.audio.text(), "test-audio");
  assert.equal(recorded.stoppedAt - recorded.startedAt, 2500);
  assert.equal(mic.instance.stops, 1);
  assert.equal(stopped, 1);
  recorder.dispose();
  assert.equal(recorder.result, null);
  assert.equal(recorder.finished, null);
  assert.deepEqual(recorder.chunks, []);
});

test("a late microphone permission result after discard is stopped without starting a recorder", async () => {
  const mic = microphone(); let allow;
  const recorder = new AudioRecorder({ environment: { ...mic.environment,
    mediaDevices: { getUserMedia: () => new Promise((resolve) => { allow = resolve; }) } } });
  const pending = recorder.start({ consentConfirmed: true });
  recorder.dispose();
  allow(mic.stream);
  assert.equal(await pending, false);
  assert.equal(mic.track.readyState, "ended");
  assert.equal(mic.instance, undefined);
});

test("denied permission and recorder start failures are reported without leaving capture tracks", async () => {
  const denied = microphone({ failure: "NotAllowedError" });
  await assert.rejects(new AudioRecorder({ environment: denied.environment }).start({ consentConfirmed: true }), { code: "NotAllowedError" });
  for (const failure of ["constructor", "start"]) {
    const mic = microphone({ recorderFailure: failure });
    await assert.rejects(new AudioRecorder({ environment: mic.environment }).start({ consentConfirmed: true }));
    assert.equal(mic.track.readyState, "ended");
  }
});

test("automatic stop leaves a margin below three minutes and reports why it stopped", async () => {
  const mic = microphone();
  const recorder = new AudioRecorder({ environment: mic.environment });
  await recorder.start({ consentConfirmed: true });
  const finished = recorder.finished;
  mic.advance(179);
  const recorded = await finished;
  assert.equal(recorded.reason, "limit");
  assert.equal(recorded.durationSeconds, 179);
  assert.equal(mic.track.readyState, "ended");
  recorder.dispose();
});

test("a suspended timer exceeding the true limit cannot produce an uploadable result", async () => {
  const mic = microphone(); let error;
  const recorder = new AudioRecorder({ environment: mic.environment, onError(value) { error = value; } });
  await recorder.start({ consentConfirmed: true });
  const finished = recorder.finished;
  mic.advance(181);
  assert.equal(await finished, null);
  assert.equal(recorder.result, null);
  assert.equal(error.code, "invalid_recording");
});

test("empty audio and oversize chunks fail and are cleared without leaking microphone tracks", async () => {
  const emptyMic = microphone({ bytes: "" }); let emptyError;
  const empty = new AudioRecorder({ environment: emptyMic.environment, onError(e) { emptyError = e; } });
  await empty.start({ consentConfirmed: true }); emptyMic.advance(1);
  assert.equal(await empty.stop(), null);
  assert.equal(emptyError.code, "invalid_recording");
  const mic = microphone(); let sizeError;
  const large = new AudioRecorder({ environment: mic.environment, onError(e) { sizeError = e; } });
  await large.start({ consentConfirmed: true });
  mic.instance.ondataavailable({ data: new Blob([new ArrayBuffer(MAX_AUDIO_BYTES + 1)]) });
  assert.equal(sizeError.code, "audio_too_large");
  assert.equal(large.result, null);
  assert.deepEqual(large.chunks, []);
  assert.equal(mic.track.readyState, "ended");
});

test("OS interruption is distinguished from a deliberate stop", async () => {
  const mic = microphone();
  const recorder = new AudioRecorder({ environment: mic.environment });
  await recorder.start({ consentConfirmed: true }); mic.advance(2);
  const finished = recorder.finished;
  mic.track.dispatchEvent(new Event("ended"));
  assert.equal((await finished).reason, "interrupted");
  recorder.dispose();
});

test("a missing stop event times out, releases capture and cannot create a partial result", async () => {
  const mic = microphone(); let expire, error;
  const recorder = new AudioRecorder({ environment: { ...mic.environment,
    setTimeout(callback) { expire = callback; return 2; }, clearTimeout() {} }, onError(e) { error = e; } });
  await recorder.start({ consentConfirmed: true }); mic.advance(2);
  mic.instance.stop = function () { this.state = "inactive"; };
  const pending = recorder.stop(); expire();
  assert.equal(await pending, null);
  assert.equal(recorder.result, null);
  assert.equal(mic.track.readyState, "ended");
  assert.match(error.message, /終了を確認できませんでした/);
});

test("discard during capture ignores queued final chunks and stops all capture tracks", async () => {
  const mic = microphone(); let notified = false;
  const recorder = new AudioRecorder({ environment: mic.environment, onStopped() { notified = true; } });
  await recorder.start({ consentConfirmed: true }); mic.advance(1);
  setRecorder(recorder);
  clearPatientData();
  await Promise.resolve();
  assert.equal(recorder.disposed, true);
  assert.equal(recorder.result, null);
  assert.equal(notified, false);
  assert.equal(mic.track.readyState, "ended");
  assert.equal(getState().recorder, null);
});

test("audio upload uses the exact multipart contract, authentication and original bytes", async () => {
  const recording = result();
  globalThis.fetch = async (url, options) => {
    assert.equal(url.pathname, "/api/drafts");
    assert.equal(options.method, "POST");
    assert.equal(options.headers.get("X-Passcode"), "test-only-passcode");
    assert.equal(options.headers.has("Content-Type"), false);
    const form = options.body;
    assert.ok(form instanceof FormData);
    assert.deepEqual([...form.keys()].sort(), ["audio", "consent_confirmed", "duration_seconds", "first_speaker", "patient_id"]);
    assert.equal(form.get("first_speaker"), "auto");
    assert.equal(form.get("patient_id"), fixture.patient.id);
    assert.equal(form.get("consent_confirmed"), "true");
    assert.equal(form.get("duration_seconds"), "2.5");
    assert.equal(form.get("audio").name, "recording.m4a");
    assert.equal(await form.get("audio").text(), await recording.audio.text());
    return Response.json(fixture);
  };
  const review = await createAudioReview(fixture.patient, recording, { consentConfirmed: true });
  assert.equal(review.audio, recording.audio);
  assert.ok(review.audioUrl);
  assert.equal(review.timing.recording_started, "2026-11-08T09:00:00.000+09:00");
  assert.equal(review.timing.recording_stopped, "2026-11-08T09:00:02.500+09:00");
  review.dispose();
});

test("missing consent or invalid audio cannot reach the backend", async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; throw new Error("must not send"); };
  await assert.rejects(createAudioReview(fixture.patient, result()), { code: "consent_required" });
  for (const recording of [null, { ...result(), audio: new Blob() }, { ...result(), durationSeconds: 181 }]) {
    await assert.rejects(createAudioReview(fixture.patient, recording, { consentConfirmed: true }), { code: "invalid_recording" });
  }
  assert.equal(calls, 0);
});

test("failed uploads preserve the recording and never auto-retry or substitute mock data", async () => {
  const recording = result(); let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return Response.json({ mode: "live", error: { code: "speech_failed", message: "文字起こしに失敗しました" } }, { status: 502 });
  };
  await assert.rejects(createAudioReview(fixture.patient, recording, { consentConfirmed: true }), { status: 502, code: "speech_failed" });
  assert.equal(calls, 1);
  assert.equal(await recording.audio.text(), "test-only-audio");
});

test("live responses use the same contract, while the wrong input or patient cannot enter review", async () => {
  globalThis.fetch = async () => Response.json({ ...fixture, mode: "live" });
  const review = await createAudioReview(fixture.patient, result(), { consentConfirmed: true });
  assert.equal(review.mode, "live"); review.dispose();
  for (const response of [{ ...fixture, input: "text" }, { ...fixture, patient: { ...fixture.patient, id: "p303" } }]) {
    globalThis.fetch = async () => Response.json(response);
    await assert.rejects(createAudioReview(fixture.patient, result(), { consentConfirmed: true }), { code: "invalid_response" });
  }
});

test("review takes ownership of the audio and clears the recorder's references", async () => {
  const mic = microphone(); const recorder = new AudioRecorder({ environment: mic.environment });
  await recorder.start({ consentConfirmed: true }); mic.advance(2);
  const recording = await recorder.stop(); setRecorder(recorder);
  globalThis.fetch = async () => Response.json(fixture);
  const review = await createAudioReview(fixture.patient, recording, { consentConfirmed: true });
  setReview(review);
  assert.equal(recorder.result, null);
  assert.equal(recorder.finished, null);
  assert.equal(getState().recorder, null);
  assert.ok(getState().review.audio);
  clearPatientData();
  assert.equal(review.audio, null);
  assert.equal(review.audioUrl, null);
});
