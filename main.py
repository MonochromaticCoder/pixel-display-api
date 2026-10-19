import base64

from soco import SoCo, discover
from time import sleep
from fastapi import FastAPI
import httpx2
from io import BytesIO
from PIL import Image

client = httpx2.Client()

zone: SoCo = [x for x in (discover() or []) if x.player_name == "Living Room"][0]

app = FastAPI()


@app.get("/")
def root():
    info = zone.get_current_track_info()
    album_art_url = info.get("album_art")
    c = None
    if album_art_url:
        print(album_art_url)
        album_art_bytes = client.get(album_art_url).raise_for_status().content
        img = Image.open(BytesIO(album_art_bytes)).convert("RGB")
        img = img.resize((8, 8), Image.Resampling.BOX)
        out = BytesIO()
        img.save(out, "GIF")
        c = "data:image/gif;base64," + base64.b64encode(out.getvalue()).decode("ascii")
    return {
        "t": info.get("title", "").replace("🄴", "").replace("🄲", "").strip(),
        "a": info.get("artist", ""),
        "c": c,
    }


@app.post("/playpause")
def playpause():
    if zone.get_current_transport_info()["current_transport_state"] in {
        "PLAYING",
        "TRANSITIONING",
    }:
        zone.pause()
    else:
        zone.play()
    return {}


@app.post("/vol_up")
def vol_up():
    zone.volume += 5
    return {}


@app.post("/vol_down")
def vol_down():
    zone.volume -= 5
    return {}


@app.post("/next")
def next():
    zone.next()
    return {}


@app.post("/prev")
def prev():
    zone.previous()
    return {}
