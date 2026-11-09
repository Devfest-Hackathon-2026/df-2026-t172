"""受け取った音声を、認識にかける形（16kHz モノラル）に直す（コンテナの中の ffmpeg）。

11/8 の技術検証で、m4a（AAC）をそのまま送ると、エラーなしで結果が空になった。
そのため、どの形式（webm/opus・mp4/AAC・m4a など）でも、一度 PCM に読み、区切ってから
FLAC にして送る。

音声は保存しない（P-01）。mp4 は末尾に目次があり標準入力からは読めないことがあるので、
読むときだけ一時ファイルに書き、読み終わったらすぐ消す。それ以外はメモリだけで扱う。
"""

import os
import subprocess
import tempfile

SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2  # 16bit・モノラル
_FFMPEG = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error"]
_TIMEOUT_SECONDS = 60


class AudioUnreadable(ValueError):
    """音声として読めなかった（形式が違う・壊れている・音がない）。"""


def decode_pcm(audio: bytes) -> bytes:
    """音声を 16kHz モノラル・16bit の PCM にする。

    Raises:
        AudioUnreadable: ffmpeg が読めなかった、または音が1つもない場合
    """
    fd, path = tempfile.mkstemp(suffix=".audio")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(audio)
        done = subprocess.run(
            [
                *_FFMPEG,
                "-i",
                path,
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(SAMPLE_RATE),
                "-f",
                "s16le",
                "pipe:1",
            ],
            capture_output=True,
            timeout=_TIMEOUT_SECONDS,
        )
    finally:
        os.remove(path)
    if done.returncode != 0 or not done.stdout:
        raise AudioUnreadable("音声を読めなかった")
    return done.stdout


def pcm_seconds(pcm: bytes) -> float:
    """PCM の長さ（秒）。"""
    return len(pcm) / BYTES_PER_SECOND


def pcm_slice(pcm: bytes, start: float, end: float) -> bytes:
    """PCM の start〜end 秒を切り出す（2バイト単位でそろえる）。"""
    a = int(start * SAMPLE_RATE) * 2
    b = int(end * SAMPLE_RATE) * 2
    return pcm[a:b]


def flac_of(pcm: bytes) -> bytes:
    """PCM を FLAC にする（メモリだけで行う）。"""
    done = subprocess.run(
        [
            *_FFMPEG,
            "-f",
            "s16le",
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            "1",
            "-i",
            "pipe:0",
            "-f",
            "flac",
            "pipe:1",
        ],
        input=pcm,
        capture_output=True,
        timeout=_TIMEOUT_SECONDS,
        check=True,
    )
    return done.stdout
