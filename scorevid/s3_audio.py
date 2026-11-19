# -*- coding: utf-8 -*-
"""第 3 步：从录音文件截出要用的部分（可剪掉中间的长静音），并算出对齐用的音频特征。

输出：
  中间文件/audio/track.wav     视频用的音轨（48 kHz 立体声，16 位）
  中间文件/audio/features.npz  对齐用特征：84 维音高谱 + 12 维色度（每 0.1 秒一帧）、能量、起音强度

截取范围：project.json 的 audio.trim = [起, 止]（原文件秒数，null = 整个文件）；
剪掉：audio.cuts = [[a, b], ...]（原文件秒数）。例：多乐章录音两部分之间 16 秒静音，剪成约 4 秒。
跑完后把打印的"时长"填回 audio.end，再听一下找到末和弦结束处填 audio.music_end。
之后所有时间（小节时间、MUSIC_*）都按剪辑后的 track.wav 计。
"""
import os, subprocess
import numpy as np
from common import NICE_CMD, FF_THREADS, MP3, MID, AUDIO_START, AUDIO_END, AUDIO_TRIM, AUDIO_CUTS, AUDIO_WAV

AUD = os.path.join(MID, "audio")
os.makedirs(AUD, exist_ok=True)
WAV = AUDIO_WAV
FEAT = os.path.join(AUD, "features.npz")
SR = 22050
HOP = 0.1


def decode(sr, ch, fmt):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", WAV, "-ac", str(ch), "-ar", str(sr), "-f", fmt, "-"]
    return subprocess.run(cmd, check=True, capture_output=True).stdout


def main():
    t0, t1 = (AUDIO_TRIM or [0.0, None])
    keep, cur = [], t0
    for a, b in sorted(AUDIO_CUTS):
        keep.append((cur, a)); cur = b
    keep.append((cur, t1))
    parts = []
    for i, (a, b) in enumerate(keep):
        end = f":end={b}" if b is not None else ""
        parts.append(f"[0:a]atrim=start={a}{end},asetpts=PTS-STARTPTS[s{i}]")
    af = ";".join(parts) + ";" + "".join(f"[s{i}]" for i in range(len(keep))) + f"concat=n={len(keep)}:v=0:a=1[o]"
    subprocess.run(NICE_CMD + ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-threads", FF_THREADS, "-i", MP3,
                    "-filter_complex", af, "-map", "[o]", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", WAV], check=True)
    x = np.frombuffer(decode(SR, 1, "f32le"), dtype=np.float32).astype(np.float64)
    print("时长", len(x) / SR, "秒")
    nfft = 8192
    hop = int(round(HOP * SR))
    win = np.hanning(nfft)
    pad = np.concatenate([np.zeros(nfft // 2), x, np.zeros(nfft // 2)])
    nfr = 1 + (len(pad) - nfft) // hop
    freqs = np.fft.rfftfreq(nfft, 1 / SR)
    # 每个 FFT 频点归到最近的半音（MIDI 24..107），只用 55 Hz–5 kHz
    midi = np.full(len(freqs), -1)
    ok = (freqs >= 55) & (freqs <= 5000)
    midi[ok] = np.round(69 + 12 * np.log2(freqs[ok] / 440.0)).astype(int)
    lo, hi = 24, 108
    pitch = np.zeros((nfr, hi - lo), np.float32)
    energy = np.zeros(nfr, np.float32)
    flux = np.zeros(nfr, np.float32)
    prev = None
    sel = np.where((midi >= lo) & (midi < hi))[0]
    tgt = midi[sel] - lo
    for i in range(nfr):
        seg = pad[i * hop: i * hop + nfft] * win
        mag = np.abs(np.fft.rfft(seg))
        energy[i] = np.sqrt(np.mean(seg ** 2) + 1e-12)
        lm = np.log1p(1000 * mag[sel])
        if prev is not None:
            flux[i] = np.maximum(lm - prev, 0).sum()
        prev = lm
        np.add.at(pitch[i], tgt, mag[sel] ** 2)
    pitch = np.log1p(100 * pitch / (pitch.max() + 1e-12) * 1000)
    chroma = np.zeros((nfr, 12), np.float32)
    for m in range(lo, hi):
        chroma[:, m % 12] += pitch[:, m - lo]
    times = np.arange(nfr) * HOP
    np.savez_compressed(FEAT, chroma=chroma, pitch=pitch, energy=energy, flux=flux, times=times,
                        hop=HOP, start=AUDIO_START, end=AUDIO_END)
    print("写出", WAV, FEAT, chroma.shape)


if __name__ == "__main__":
    main()
