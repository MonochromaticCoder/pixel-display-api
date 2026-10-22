import base64
import json

from soco import SoCo, discover
from soco.data_structures import DidlMusicTrack
from time import sleep
from fastapi import FastAPI
import httpx2
from io import BytesIO
from PIL import Image
from time import sleep
import threading
from queue import Empty
from soco.events import Subscription, Event
from paho.mqtt import client as mqtt

mqtt_client = mqtt.Client(client_id="pixel-display-api")
mqtt_client.connect_async("192.168.48.100", 1883, keepalive=60)
mqtt_client.loop_start()


def publish(topic: str, payload, retain: bool = True):
    if not isinstance(payload, str):
        payload = json.dumps(payload)
    mqtt_client.publish(topic, payload, retain=retain, qos=0)


client = httpx2.Client()

zone: SoCo = [x for x in (discover() or []) if x.player_name == "Living Room"][0]

sub: Subscription = zone.avTransport.subscribe()
stop = threading.Event()


# Sonos drops subscribers that stay quiet: renew in the background
def renew():
    while not stop.wait(240):
        try:
            sub.renew()
        except Exception as e:
            print("renew failed:", e)


threading.Thread(target=renew, daemon=True).start()


def sonos_to_mqtt():
    last_track: tuple[str, str, str] | None = None
    while True:
        try:
            ev: Event = sub.events.get(timeout=0.5)
        except Empty:
            continue
        track: DidlMusicTrack = ev.variables.get("current_track_meta_data")
        if track:
            track_dict = track.to_dict()
            cur_track = (
                track_dict.get("title", "").strip(),
                track_dict.get("creator", "").strip(),
                track_dict.get("album_art_uri", "").strip(),
            )
            if cur_track != last_track:
                last_track = cur_track
                if cur_track[0]:
                    t, a, c = cur_track
                    if c:
                        try:
                            album_art_bytes = client.get(c).raise_for_status().content
                            img = Image.open(BytesIO(album_art_bytes)).convert("RGB")
                            img = img.resize((8, 8), Image.Resampling.BOX)
                            out = BytesIO()
                            img.save(out, "GIF")
                            c = "data:image/gif;base64," + base64.b64encode(
                                out.getvalue()
                            ).decode("ascii")
                        except:
                            pass
                    publish(
                        "sonos/now",
                        {
                            "t": t.replace("🄴", "").replace("🄲", "").strip(),
                            "a": a,
                            "c": c,
                        },
                    )
                    publish("c885410ecd3c/cmd/apps/switch", "Sonos")
                else:
                    publish("c885410ecd3c/cmd/apps/switch", "Weather")
        else:
            publish("c885410ecd3c/cmd/apps/switch", "Weather")


threading.Thread(target=sonos_to_mqtt, daemon=True).start()


app = FastAPI()


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
    zone.play()
    return {}


@app.post("/prev")
def prev():
    zone.previous()
    zone.play()
    return {}
