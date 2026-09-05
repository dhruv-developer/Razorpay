"""Render the narration to per-scene audio with the macOS speech synthesiser."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from script import RATE, SCENES, VOICE  # noqa: E402

OUT = Path(__file__).parent / "out" / "audio"


def duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0.0
    words = 0
    print(f"voice={VOICE}  rate={RATE}wpm\n")
    for scene in SCENES:
        aiff = OUT / f"{scene['id']}.aiff"
        wav = OUT / f"{scene['id']}.wav"
        subprocess.run(
            ["say", "-v", VOICE, "-r", str(RATE), "-o", str(aiff), scene["narration"]],
            check=True,
        )
        # normalise loudness so no scene is noticeably quieter than its neighbours
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff),
             "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-ac", "2", str(wav)],
            check=True,
        )
        seconds = duration(wav)
        total += seconds
        count = len(scene["narration"].split())
        words += count
        print(f"  {scene['id']:14} {seconds:6.1f}s  {count:4} words")
        aiff.unlink()

    minutes, secs = divmod(round(total), 60)
    print(f"\n  total {minutes}:{secs:02d}  ({words} words across {len(SCENES)} scenes)")


if __name__ == "__main__":
    main()
