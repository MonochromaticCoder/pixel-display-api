import base64
import json

from soco import SoCo, discover
from soco.data_structures import DidlMusicTrack
from time import sleep
from fastapi import FastAPI, Response
import httpx2
from io import BytesIO
from PIL import Image
from time import sleep
import threading
from queue import Empty
from soco.events import Subscription, Event
from paho.mqtt import client as mqtt
import asyncio
from sonos_websocket.websocket import SonosWebsocket
import os
from openai import OpenAI
import uuid

inference = OpenAI(
    base_url=os.getenv("INFERENCE_BASE_URL"),
    api_key=os.getenv("INFERENCE_API_KEY"),
    timeout=None,
)


async def notify(ip: str, clip_uri: str):
    ws = SonosWebsocket(ip)
    await ws.connect()
    await ws.play_clip(uri=clip_uri, volume=70)
    await ws.close()


mqtt_client = mqtt.Client(client_id="pixel-display-api")
mqtt_client.connect("192.168.48.200", 1883, keepalive=60)
mqtt_client.loop_start()


def publish(topic: str, payload, retain: bool = True):
    if not isinstance(payload, str):
        payload = json.dumps(payload)
    mqtt_client.publish(topic, payload, retain=retain, qos=0)


def on_message(client, userdata, msg):
    try:
        message: dict = json.loads(msg.payload.decode())
        sound_id = str(uuid.uuid4())
        res = inference.audio.speech.create(
            model="breeze-tts-2",
            voice=message["voice"],
            input=message["content"],
        )
        sounds[sound_id] = res.content
        asyncio.run(
            notify(
                zone.ip_address,
                f"{os.getenv('SELF_URL')}/notification_sound/{sound_id}",
            )
        )
    except:
        pass


mqtt_client.subscribe("sonos/speak")
mqtt_client.on_message = on_message


client = httpx2.Client()

zone: SoCo = [x for x in (discover() or []) if x.player_name == "Living Room"][0]

sub: Subscription = zone.avTransport.subscribe()
stop = threading.Event()
sounds: dict[str, bytes] = {}


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


@app.get("/notification_sound/{sound_id}")
def notification_sound(sound_id: str):
    return Response(content=sounds.pop(sound_id), media_type="audio/wav")
