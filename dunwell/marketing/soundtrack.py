"""Synthesise the soundtrack for video.html (music bed + synced sound effects).

Everything is generated from code (no samples, no licensed music), seeded so
the output is identical on every run. Event times mirror renderAt() in
video.html; if you retime the animation, retime the cues in CUES below.

    python soundtrack.py out/dunwell.wav      # needs numpy
"""
import sys
import wave

import numpy as np

SR = 48000
DUR = 20.0
N = int(SR * DUR)
RNG = np.random.default_rng(7)


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def ts(dur):
    return np.arange(int(dur * SR)) / SR


class Mix:
    def __init__(self):
        self.buf = np.zeros((N, 2))

    def add(self, sig, at, gain=1.0, pan=0.0):
        i = int(at * SR)
        if i >= N:
            return
        sig = sig[: N - i] * gain
        self.buf[i:i + len(sig), 0] += sig * np.sqrt((1 - pan) / 2)
        self.buf[i:i + len(sig), 1] += sig * np.sqrt((1 + pan) / 2)


def lowpass(x, cutoff):
    """One-pole lowpass; cutoff may be a scalar or a per-sample array."""
    cutoff = np.broadcast_to(np.asarray(cutoff, float), x.shape)
    a = 1 - np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    s = 0.0
    for i in range(len(x)):
        s += a[i] * (x[i] - s)
        y[i] = s
    return y


def noise(dur):
    return RNG.standard_normal(int(dur * SR))


# ---------- instruments ----------

def pad_note(f, dur, attack=0.6, release=0.8):
    t = ts(dur)
    sig = sum(np.sin(2 * np.pi * f * h * d * t + h) / h ** 1.6
              for h in range(1, 7) for d in (0.997, 1.003))
    env = np.minimum(1, t / attack) * np.minimum(1, (dur - t) / release).clip(0)
    return sig * env * 0.18


def pluck(f, dur=0.45):
    t = ts(dur)
    return (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(4 * np.pi * f * t)) * np.exp(-t * 7)


def kick():
    t = ts(0.35)
    f = 45 + 110 * np.exp(-t * 28)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 11)


def hat():
    n = noise(0.05)
    return (n - lowpass(n, 6000)) * np.exp(-ts(0.05) * 90)


def thud(depth=1.0):
    t = ts(0.4)
    f = 40 + 90 * np.exp(-t * 22)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 14)
    click = lowpass(noise(0.4), 2500) * np.exp(-t * 60) * 0.6
    return (body + click) * depth


def pop(f0, f1, dur=0.12):
    t = ts(dur)
    f = f1 + (f0 - f1) * np.exp(-t * 40)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 28)


def tick(bright=3500):
    n = noise(0.02)
    return (n - lowpass(n, bright)) * np.exp(-ts(0.02) * 300)


def bell(f, dur=1.6):
    t = ts(dur)
    return sum(a * np.sin(2 * np.pi * f * r * t) * np.exp(-t * k)
               for r, a, k in ((1, 1, 2.2), (2.0, .35, 3.5), (2.76, .25, 5), (5.4, .12, 8)))


def whoosh(dur, lo, hi, rise=True):
    t = ts(dur)
    p = t / dur
    cut = lo + (hi - lo) * (p if rise else 1 - p) ** 2
    env = np.sin(np.pi * p) ** 1.5
    return lowpass(noise(dur), cut) * env


def swell(dur):
    t = ts(dur)
    p = t / dur
    return lowpass(noise(dur), 300 + 3500 * p ** 3) * p ** 3


def scribble(dur):
    t = ts(dur)
    n = noise(dur)
    band = lowpass(n, 3000) - lowpass(n, 900)
    return band * (0.5 + 0.5 * np.sin(2 * np.pi * 9 * t) ** 2) * np.minimum(1, (dur - t) * 12)


# ---------- score ----------

CHORDS = [  # (start, end, bass midi, pad midis)
    (0.0, 3.4, 45, [57, 60, 64]),         # Am  - the problem
    (3.4, 6.6, 41, [57, 60, 65]),         # F   - the rules
    (6.6, 9.8, 48, [55, 60, 64]),         # C   - the maths
    (9.8, 13.6, 43, [55, 59, 62, 67]),    # G   - the letter
    (13.6, 14.95, 40, [57, 59, 64]),      # Esus - held breath before the send
    (14.95, 20.0, 48, [60, 64, 67, 72]),  # C   - paid, bright resolve
]
BEAT = 0.5  # 120 bpm


def beats(a, b):
    k = np.ceil(a / BEAT - 1e-9)
    while k * BEAT < b - 1e-9:
        yield k * BEAT
        k += 1


def counter_ticks():
    # One tick per €5 the counter moves; follows the same ease-out as the numbers.
    out = []
    for k in range(1, 27):
        f = min(1, k * 5 / 132.56)
        out.append(7.95 + 1.05 * (1 - (1 - f) ** (1 / 3)))
    return out


def build():
    m = Mix()

    # music bed
    for a, b, bass, notes in CHORDS:
        for j, n in enumerate(notes):
            m.add(pad_note(hz(n), b - a + 0.8), a, 0.55, pan=(j / max(1, len(notes) - 1) - .5) * .6)
        m.add(pad_note(hz(bass), b - a + 0.8), a, 0.5)
        if 3.4 <= a < 13.6 or a == 14.95:
            end = min(b, 16.4)
            for x in beats(a, end):
                m.add(pluck(hz(bass + 12)), x, .22, pan=-.1)
    for x in list(beats(6.6, 13.6)) + list(beats(14.95, 16.4)):
        m.add(kick(), x, .55)
    for x in list(beats(9.8, 13.6)) + list(beats(14.95, 16.4)):
        m.add(hat(), x + BEAT / 2, .18, pan=.3)

    # S1: invoice falls and lands, stamp slams
    m.add(whoosh(0.55, 200, 2200), 0.28, .35)
    m.add(thud(.8), 0.82, .9)
    m.add(whoosh(0.35, 300, 3000), 1.57, .25)
    m.add(thud(1.2), 1.92, 1.1)
    m.add(tick(1500), 1.92, .9)

    # S2: the two add-ons drop in
    for at, pan, f in ((4.3, .35, 880), (4.63, .45, 1175)):
        m.add(whoosh(0.3, 400, 3500), at - .3, .18, pan)
        m.add(pop(f, f / 2), at, .5, pan)
        m.add(thud(.35), at, .5, pan)

    # S3: scan sweep, counter ticks, lock-in ding
    m.add(whoosh(0.9, 500, 5000), 6.9, .22, -.2)
    t = ts(0.9)
    m.add(np.sin(2 * np.pi * np.cumsum(500 + 700 * (t / .9) ** 2) / SR) * np.sin(np.pi * t / .9) * .15, 6.9, .6)
    for x in counter_ticks():
        m.add(tick(), x, .55, .15)
    m.add(bell(hz(84)), 9.0, .35)
    m.add(bell(hz(91)), 9.04, .18, .3)

    # S4: letter arrives, types itself, signs, cycles languages
    m.add(whoosh(0.6, 300, 2500, rise=False), 10.2, .3, .3)
    m.add(thud(.3), 10.85, .4)
    x = 10.7
    while x < 11.55:
        m.add(tick(4500), x, .22 + .1 * RNG.random(), RNG.uniform(-.3, .3))
        x += 0.035 + 0.03 * RNG.random()
    m.add(scribble(0.5), 11.7, .09, -.15)
    for i, at in enumerate((12.3, 12.62, 12.94, 13.26)):
        f = hz((76, 79, 81, 84)[i])
        m.add(pop(f * 1.5, f, .16), at, .45, (-.4, -.1, .2, .45)[i])

    # S5: breath in, launch, paid
    m.add(swell(0.35), 13.66, .35)
    m.add(whoosh(0.55, 600, 7000), 14.0, .7, .5)
    m.add(whoosh(0.4, 300, 2000), 14.6, .25)
    m.add(thud(1.3), 14.98, 1.0)
    for i, n in enumerate((72, 76, 79, 84)):
        m.add(bell(hz(n)), 15.08 + i * .07, .3, (-.3, -.1, .1, .3)[i])

    # S6: logo hit, letters tick in, underline swoosh
    m.add(thud(1.4), 16.62, .8)
    m.add(bell(hz(60), 3.0), 16.62, .25)
    for i in range(7):
        m.add(tick(5000), 16.62 + i * .05, .25, (i - 3) / 6)
    m.add(whoosh(0.55, 800, 6000), 17.25, .22, .2)
    m.add(bell(hz(88), 2.2), 17.8, .12, .3)

    # light reverb: convolve with a decaying noise tail per channel
    irt = ts(1.4)
    out = np.empty_like(m.buf)
    for ch in range(2):
        ir = RNG.standard_normal(len(irt)) * np.exp(-irt / .32)
        ir /= np.sqrt((ir ** 2).sum())
        L = 1 << int(np.ceil(np.log2(N + len(ir))))
        wet = np.fft.irfft(np.fft.rfft(m.buf[:, ch], L) * np.fft.rfft(ir, L), L)[:N]
        out[:, ch] = m.buf[:, ch] + .22 * wet

    t = np.arange(N) / SR
    out *= np.minimum(1, t / .05)[:, None] * np.clip((DUR - t) / 1.2, 0, 1)[:, None]
    out = np.tanh(out / np.abs(out).max() * 1.2) / np.tanh(1.2) * 0.89  # ~-1 dBFS
    return out


def write(path):
    pcm = (build() * 32767).astype('<i2')
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


if __name__ == '__main__':
    write(sys.argv[1] if len(sys.argv) > 1 else 'dunwell.wav')
