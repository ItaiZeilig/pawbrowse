"""Render a side-by-side AGENT-TIME benchmark: same task, same agent, same site, two tools.

Unlike render_compare.py (which clocks browser-side wall-time), this clocks AGENT ROUND-TRIPS: every
tool call is one agent round-trip, and the clock = round-trips x a fixed per-call latency that is the
SAME for both tools (same model). So the gap is purely the structural one: PawBrowse acts in 1 call
per action (its act returns the fresh element table), Claude in Chrome must perceive-then-act. Frames
are the real captures from each run; the round-trip counts are the real calls each tool made.

    python3 scripts/demo/render_race.py <config.json>
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
cfg = json.loads(Path(sys.argv[1]).read_text())

L = cfg.get("latency_s", 2.0)      # seconds per agent round-trip (same for both tools)
PACE = cfg.get("pace", 0.55)        # video seconds per agent second
FPS = 30
HOLD = 2.2                          # seconds held on the final frame
W, H = 1536, 1000
BG, PANEL, EDGE = "#0b1119", "#111a26", "#1f2a38"
INK, MUTED, DIM = "#f1f5f9", "#8b98a9", "#4b5a6d"
GREEN, DOTOFF = "#22c55e", "#31415a"


def font(n, bold=False):
    base = "/System/Library/Fonts/Supplemental/"
    p = base + ("Arial Bold.ttf" if bold else "Arial.ttf")
    return ImageFont.truetype(p, n) if Path(p).exists() else ImageFont.load_default(n)


def mono(n, bold=False):
    p = "/System/Library/Fonts/Menlo.ttc"
    return ImageFont.truetype(p, n) if Path(p).exists() else ImageFont.load_default(n)


class Run:
    def __init__(self, c):
        self.name = c["name"]
        self.color = c["color"]
        self.per = c["calls_per_action"]           # calls each action costs (e.g. [1,1,1,1,1])
        self.total_calls = sum(self.per)
        self.tag = c["tag"]                         # e.g. "1 call / action"
        self.result = c["result"]
        d = Path(c["dir"])
        idx = c["frames"]                          # [start, after-a1, ..., after-aN]
        self.imgs = [Image.open(d / f"{i:05d}.jpg").convert("RGB") for i in idx]
        # agent-time (s) at which each action completes: cumulative calls * L
        self.done_at = []
        acc = 0
        for p in self.per:
            acc += p
            self.done_at.append(acc * L)
        self.finish = self.total_calls * L

    def state(self, tau):
        """actions completed, calls used, clock (s) at agent-time tau."""
        acts = sum(1 for t in self.done_at if tau >= t - 1e-6)
        calls = min(self.total_calls, int(round(tau / L + 1e-6)))
        clock = min(tau, self.finish)
        return acts, calls, clock

    def frame(self, acts):
        return self.imgs[min(acts, len(self.imgs) - 1)]


runs = [Run(c) for c in cfg["runs"]]
T = max(r.finish for r in runs)                    # agent-seconds to play
total = int(round((T * PACE + HOLD) * FPS))
labels = cfg["actions"]

out = Path("/tmp/bench/race-frames")
if out.exists():
    shutil.rmtree(out)
out.mkdir(parents=True)
paw = Image.open(ROOT / "extension/icons/icon-128.png").convert("RGBA").resize((30, 30), Image.LANCZOS)

COLW, GAP, X0 = 724, 16, 36
FY = 250
PH = 360


def rt(d, box, **kw):
    d.rounded_rectangle(box, **kw)


for i in range(total):
    vt = i / FPS                                   # video seconds
    tau = min(vt / PACE, T)                        # agent seconds
    c = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(c)
    c.paste(paw, (36, 22), paw)
    d.text((76, 24), "PawBrowse", font=font(23, True), fill=INK)
    d.text((76 + d.textlength("PawBrowse", font=font(23, True)) + 10, 27), "benchmark", font=font(19), fill=MUTED)
    badge = "REAL RUNS  ·  CLOCK = AGENT ROUND-TRIPS"
    bw = d.textlength(badge, font=font(13, True)) + 36
    d.rounded_rectangle((W - 36 - bw, 22, W - 36, 54), radius=16, outline=GREEN, width=2)
    d.text((W - 36 - bw + 18, 31), badge, font=font(13, True), fill=GREEN)
    d.text((36, 68), cfg["title"], font=font(34, True), fill=INK)
    d.text((38, 114), cfg["subtitle"], font=font(18), fill=MUTED)

    for k, r in enumerate(runs):
        x = X0 + k * (COLW + GAP)
        acts, calls, clock = r.state(tau)
        done = tau >= r.finish
        col = r.color
        d.text((x, 162), r.name, font=font(24, True), fill=col)
        d.text((x, 196), r.tag, font=font(16, True), fill=MUTED)
        # big clock
        clk = f"{clock:5.1f}s"
        d.text((x + COLW - d.textlength(clk, font=mono(30, True)), 168), clk, font=mono(30, True), fill=col if done else INK)
        d.text((x + COLW - d.textlength(f"{calls} round-trips", font=font(15)), 208), f"{calls} round-trips", font=font(15), fill=MUTED)
        # frame
        img = r.frame(acts)
        c.paste(img.resize((COLW, round(img.height * COLW / img.width)), Image.LANCZOS).crop((0, 0, COLW, PH)), (x, FY))
        d.rounded_rectangle((x - 1, FY - 1, x + COLW + 1, FY + PH + 1), radius=10, outline=col if done else EDGE, width=2 if done else 1)
        # round-trip dots
        dy = FY + PH + 20
        n = r.total_calls
        gapd = min(26, (COLW - 10) // n)
        for j in range(n):
            cx = x + 6 + j * gapd
            fill = col if j < calls else DOTOFF
            d.ellipse((cx, dy, cx + 13, dy + 13), fill=fill)
        d.text((x, dy + 24), f"one dot = one agent round-trip  ({n} total)", font=font(13), fill=DIM)
        # action checklist
        cy = dy + 52
        for j, name in enumerate(labels):
            y = cy + j * 30
            ok = acts > j
            if ok:
                d.ellipse((x, y, x + 20, y + 20), fill=col)
                d.line([(x + 5, y + 10), (x + 9, y + 14), (x + 15, y + 6)], fill=BG, width=3)
            else:
                d.ellipse((x, y, x + 20, y + 20), outline=DIM, width=2)
            d.text((x + 32, y), name, font=font(17, ok), fill=INK if ok else MUTED)
        # result / status
        by = cy + len(labels) * 30 + 12
        if done:
            d.rounded_rectangle((x, by, x + COLW, by + 66), radius=10, fill="#0f2a1c" if k == 0 else "#241016", outline=col)
            d.text((x + 16, by + 12), f"Done · {r.total_calls} round-trips · {r.finish:.1f}s", font=font(19, True), fill=col)
            d.text((x + 16, by + 40), r.result, font=font(15), fill=INK)
        else:
            d.rounded_rectangle((x, by, x + COLW, by + 66), radius=10, fill=PANEL, outline=EDGE)
            d.text((x + 16, by + 22), "working…", font=font(18), fill=DIM)

    d.text((36, 958), cfg["footnote"], font=font(13), fill=MUTED)
    d.text((36, 976), cfg["footnote2"], font=font(13), fill=MUTED)
    c.save(out / f"{i:05d}.png")

dest = ROOT / "assets"
c.save(dest / "benchmark-result.png")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(out / "%05d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart",
                str(dest / "benchmark.mp4")], check=True)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(dest / "benchmark.mp4"), "-vf",
                "fps=12,scale=1152:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
                "-loop", "0", str(dest / "benchmark.gif")], check=True)
print("rendered", total, "frames ->", dest / "benchmark.gif")
