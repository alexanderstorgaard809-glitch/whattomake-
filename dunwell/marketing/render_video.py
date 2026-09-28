"""Render video.html to MP4 (16:9 and 9:16).

Needs: pip install playwright imageio-ffmpeg  (and a Chromium for Playwright).

    python render_video.py                 # both formats into ./out
    python render_video.py --stills 1,5,9  # PNG stills at those seconds instead

Each frame is rendered independently by calling renderAt(t) in the page,
screenshotted, and piped to ffmpeg as H.264.
"""
import argparse
import os
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
FORMATS = {"16x9": (1920, 1080), "9x16": (1080, 1920)}


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def render(page, fmt, out, fps, stills):
    w, h = FORMATS[fmt]
    page.set_viewport_size({"width": w, "height": h})
    page.goto((HERE / "video.html").as_uri() + f"?f={fmt}")
    page.wait_for_function("window.ready === true")
    if stills:
        for s in stills:
            page.evaluate(f"renderAt({s})")
            page.screenshot(path=str(out / f"dunwell-{fmt}-{s}s.png"))
        return
    duration = page.evaluate("window.DURATION")
    path = out / f"dunwell-{fmt}.mp4"
    proc = subprocess.Popen(
        [ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps),
         "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "18",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)],
        stdin=subprocess.PIPE)
    for i in range(int(duration * fps) + 1):
        page.evaluate(f"renderAt({i / fps})")
        proc.stdin.write(page.screenshot(type="png"))
    proc.stdin.close()
    proc.wait()
    print("wrote", path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--formats", default="16x9,9x16")
    ap.add_argument("--stills", default="")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stills = [float(s) for s in a.stills.split(",") if s]
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("CHROME_PATH") or None)
        page = browser.new_page()
        for fmt in a.formats.split(","):
            render(page, fmt, out, a.fps, stills)
        browser.close()


if __name__ == "__main__":
    main()
