"""Screen-record the running app, scene by scene, over the DevTools Protocol.

Chrome is launched headless against a throwaway profile, authenticated by
writing the session token into localStorage, then driven through each scene
while `Page.startScreencast` streams real frames. Every scene is held for
exactly the length of its voiceover, so picture and narration stay in step.
"""

from __future__ import annotations

import asyncio
import base64
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
import websockets

sys.path.insert(0, str(Path(__file__).parent))
from script import SCENES, WEB  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE = Path("/tmp/bb-demo-profile")
PORT = 9333
WIDTH, HEIGHT = 1920, 1080
OUT = Path(__file__).parent / "out"
FRAMES = OUT / "frames"
API = "http://127.0.0.1:8000"


def audio_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def login_token() -> str:
    res = httpx.post(
        f"{API}/v1/auth/login",
        json={"email": "merchant@atlas.local", "password": "atlas-demo-change-me"},
        timeout=30,
    )
    res.raise_for_status()
    return res.json()["access_token"]


class Chrome:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.ws: websockets.WebSocketClientProtocol | None = None
        self._id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._frames: list[tuple[float, bytes]] | None = None
        self._reader: asyncio.Task | None = None

    # -- lifecycle ---------------------------------------------------------
    def launch(self) -> None:
        if PROFILE.exists():
            shutil.rmtree(PROFILE)
        self.proc = subprocess.Popen(
            [
                CHROME,
                "--headless=new",
                f"--remote-debugging-port={PORT}",
                f"--user-data-dir={PROFILE}",
                f"--window-size={WIDTH},{HEIGHT}",
                "--hide-scrollbars",
                "--force-device-scale-factor=1",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--force-color-profile=srgb",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(60):
            try:
                httpx.get(f"http://127.0.0.1:{PORT}/json/version", timeout=1)
                return
            except Exception:  # noqa: BLE001 - just waiting for the port
                time.sleep(0.5)
        raise RuntimeError("Chrome did not expose its debugging port")

    async def connect(self) -> None:
        targets = httpx.get(f"http://127.0.0.1:{PORT}/json/list", timeout=10).json()
        page = next(t for t in targets if t["type"] == "page")
        self.ws = await websockets.connect(page["webSocketDebuggerUrl"], max_size=64 * 1024 * 1024)
        self._reader = asyncio.create_task(self._read_loop())
        await self.send("Page.enable")
        await self.send("Runtime.enable")
        await self.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": WIDTH, "height": HEIGHT, "deviceScaleFactor": 1, "mobile": False},
        )

    async def close(self) -> None:
        if self._reader:
            self._reader.cancel()
        if self.ws:
            await self.ws.close()
        if self.proc:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        if PROFILE.exists():
            shutil.rmtree(PROFILE, ignore_errors=True)

    # -- protocol ----------------------------------------------------------
    async def _read_loop(self) -> None:
        assert self.ws
        async for raw in self.ws:
            message = json.loads(raw)
            if "id" in message:
                future = self._pending.pop(message["id"], None)
                if future and not future.done():
                    future.set_result(message)
            elif message.get("method") == "Page.screencastFrame":
                params = message["params"]
                if self._frames is not None:
                    self._frames.append((time.perf_counter(), base64.b64decode(params["data"])))
                await self.ws.send(
                    json.dumps(
                        {
                            "id": self._next_id(),
                            "method": "Page.screencastFrameAck",
                            "params": {"sessionId": params["sessionId"]},
                        }
                    )
                )

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    async def send(self, method: str, params: dict | None = None, timeout: float = 45.0) -> dict:
        assert self.ws
        message_id = self._next_id()
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[message_id] = future
        await self.ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        return await asyncio.wait_for(future, timeout)

    async def eval(self, expression: str, await_promise: bool = False) -> dict:
        """Evaluate in the page and hand back the inner RemoteObject ({type, value})."""
        response = await self.send(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": await_promise, "returnByValue": True},
        )
        return response.get("result", {}).get("result", {})

    # -- driving -----------------------------------------------------------
    async def goto(self, url: str, settle: float = 3.0) -> None:
        await self.send("Page.navigate", {"url": url})
        await asyncio.sleep(settle)
        # the dev-server badge is not part of the product
        await self.eval(
            "(() => { let s = document.getElementById('demo-hide');"
            " if (!s) { s = document.createElement('style'); s.id = 'demo-hide';"
            " s.textContent = 'nextjs-portal,#__next-build-watcher{display:none!important}';"
            " document.head.appendChild(s); } return true; })()"
        )

    async def click_text(self, label: str) -> None:
        """Click the first button/label whose text matches, via a real mouse event."""
        result = await self.eval(
            f"""(() => {{
              const want = {json.dumps(label)};
              const nodes = [...document.querySelectorAll('button, label, a, [role=tab]')];
              const el = nodes.find(n => (n.innerText || '').trim().startsWith(want));
              if (!el) return null;
              el.scrollIntoView({{block:'center'}});
              const r = el.getBoundingClientRect();
              return {{x: r.left + r.width/2, y: r.top + r.height/2}};
            }})()"""
        )
        point = result.get("value")
        if not point:
            print(f"      ! could not find '{label}'")
            return
        for kind in ("mousePressed", "mouseReleased"):
            await self.send(
                "Input.dispatchMouseEvent",
                {"type": kind, "x": point["x"], "y": point["y"], "button": "left", "clickCount": 1},
            )
        await asyncio.sleep(0.15)

    async def smooth_scroll(self, target: int, over: float) -> None:
        start = float((await self.eval("window.scrollY")).get("value") or 0)
        steps = max(1, int(over * 30))
        for i in range(1, steps + 1):
            # ease-in-out so the pan starts and stops gently
            t = i / steps
            eased = 3 * t * t - 2 * t * t * t
            await self.eval(f"window.scrollTo(0, {start + (target - start) * eased})")
            await asyncio.sleep(over / steps)

    # -- capture -----------------------------------------------------------
    async def record(self, seconds: float, steps: list[dict]) -> list[tuple[float, bytes]]:
        self._frames = []
        await self.send(
            "Page.startScreencast",
            {"format": "jpeg", "quality": 82, "maxWidth": WIDTH, "maxHeight": HEIGHT, "everyNthFrame": 1},
        )
        started = time.perf_counter()

        async def run_steps() -> None:
            for step in steps:
                if "wait" in step:
                    await asyncio.sleep(step["wait"])
                elif "scroll_to" in step:
                    await self.smooth_scroll(step["scroll_to"], step.get("over", 3.0))
                elif "click_text" in step:
                    await self.click_text(step["click_text"])
                elif "js" in step:
                    await self.eval(step["js"])

        task = asyncio.create_task(run_steps())
        # hold the scene for the full narration, whatever the steps do
        while time.perf_counter() - started < seconds:
            await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.sleep(0.05)
        await self.send("Page.stopScreencast")
        frames = self._frames
        self._frames = None
        return [(t - started, data) for t, data in frames]


def write_scene(scene_id: str, frames: list[tuple[float, bytes]], seconds: float) -> Path:
    """Write frames plus an ffmpeg concat list that reproduces their real timing."""
    folder = FRAMES / scene_id
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)

    if not frames:
        raise RuntimeError(f"{scene_id}: no frames captured")

    listing = []
    for index, (stamp, data) in enumerate(frames):
        path = folder / f"{index:05d}.jpg"
        path.write_bytes(data)
        nxt = frames[index + 1][0] if index + 1 < len(frames) else seconds
        listing.append((path, max(0.02, nxt - stamp)))

    concat = folder / "frames.txt"
    with concat.open("w") as handle:
        for path, hold in listing:
            handle.write(f"file '{path.name}'\nduration {hold:.4f}\n")
        handle.write(f"file '{listing[-1][0].name}'\n")  # concat demuxer needs the last frame repeated
    return concat


async def main() -> None:
    FRAMES.mkdir(parents=True, exist_ok=True)
    token = login_token()
    chrome = Chrome()
    chrome.launch()
    await chrome.connect()
    try:
        # authenticate + pin the dark theme before any scene is recorded
        await chrome.goto(f"{WEB}/login", settle=4.0)
        await chrome.eval(
            f"localStorage.setItem('bb_token', {json.dumps(token)});"
            "localStorage.setItem('bb_theme','dark');"
        )

        for scene in SCENES:
            audio = OUT / "audio" / f"{scene['id']}.wav"
            seconds = audio_duration(audio)
            if scene["route"]:
                await chrome.goto(f"{WEB}{scene['route']}", settle=4.5)
            print(f"  {scene['id']:14} recording {seconds:5.1f}s …", end="", flush=True)
            frames = await chrome.record(seconds, scene["steps"])
            write_scene(scene["id"], frames, seconds)
            print(f" {len(frames)} frames")
    finally:
        await chrome.close()


if __name__ == "__main__":
    asyncio.run(main())
