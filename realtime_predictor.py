"""
SleepSense AI - Real-Time Predictor + Dashboard Server
=======================================================
Subscribes to esp32/heartrate on HiveMQ Cloud,
runs sleep-stage inference, serves a live dashboard.

    python realtime_predictor.py
"""

from __future__ import annotations
import asyncio, json, os, ssl, time, threading
from collections import deque
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import paho.mqtt.client as mqtt

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
MODEL_PATH = BASE_DIR / "sleep_model.joblib"
CONFIG_PATH= BASE_DIR / "feature_config.json"
DASH_DIR   = BASE_DIR / "dashboard"

# ── HiveMQ ───────────────────────────────────────────────────────────────────
HIVEMQ_HOST = "indigobumble-39b622a1.a02.usw2.aws.hivemq.cloud"
HIVEMQ_PORT = 8883
HIVEMQ_USER = os.getenv("HIVEMQ_USER", "hivemq.webclient.1776682804651")
HIVEMQ_PASS = os.getenv("HIVEMQ_PASS", 'Up:#KhGRYou7g603Q>l<')
MQTT_TOPIC  = "esp32/heartrate"          # <-- your ESP32's topic
WINDOW_SIZE = 64

# ── Load model ───────────────────────────────────────────────────────────────
print("Loading model ...", end=" ", flush=True)
artifact      = joblib.load(MODEL_PATH)
model         = artifact["model"]
label_encoder = artifact["label_encoder"]
feature_names = artifact["feature_names"]
print(f"OK  ({len(feature_names)} features, acc={artifact['accuracy']:.4f})")

with open(CONFIG_PATH) as f:
    feature_config = json.load(f)

# ── Sensor buffer ────────────────────────────────────────────────────────────
class SensorBuffer:
    def __init__(self, win=WINDOW_SIZE):
        self.win = win
        self.ax = deque(maxlen=win*2); self.ay = deque(maxlen=win*2)
        self.az = deque(maxlen=win*2); self.hr = deque(maxlen=win*2)

    def add(self, x, y, z, h):
        self.ax.append(x); self.ay.append(y); self.az.append(z); self.hr.append(h)

    @property
    def ready(self): return len(self.ax) >= self.win
    @property
    def count(self): return len(self.ax)

    def features(self):
        if not self.ready: return None
        ax=np.array(self.ax,dtype=np.float32); ay=np.array(self.ay,dtype=np.float32)
        az=np.array(self.az,dtype=np.float32); hr=np.array(self.hr,dtype=np.float32)
        ci=len(ax)-1; w=self.win
        ax_w=ax[max(0,ci-w+1):ci+1]; ay_w=ay[max(0,ci-w+1):ci+1]
        az_w=az[max(0,ci-w+1):ci+1]; hr_w=hr[max(0,ci-w+1):ci+1]
        mag=np.sqrt(ax**2+ay**2+az**2); mag_w=mag[max(0,ci-w+1):ci+1]
        f={}
        f["acc_x"]=ax[ci]; f["acc_y"]=ay[ci]; f["acc_z"]=az[ci]
        f["hr"]=hr[ci]; f["acc_mag"]=mag[ci]
        for n,d in [("acc_x",ax_w),("acc_y",ay_w),("acc_z",az_w),("hr",hr_w),("acc_mag",mag_w)]:
            f[f"{n}_roll_mean"]=np.mean(d); f[f"{n}_roll_std"]=np.std(d)
            f[f"{n}_roll_min"]=np.min(d);   f[f"{n}_roll_max"]=np.max(d)
        f["movement_intensity"]=np.std(mag_w)
        f["hr_delta"]=float(hr[ci]-hr[ci-1]) if ci>0 else 0.0
        hd=np.diff(hr_w); f["hr_delta_roll_mean"]=float(np.mean(hd)) if len(hd)>0 else 0.0
        for n,d in [("acc_x",ax_w),("acc_y",ay_w),("acc_z",az_w)]:
            f[f"{n}_roll_range"]=float(np.max(d)-np.min(d))
        for lag in [1,2,3,5,10]:
            i=max(0,ci-lag); f[f"acc_mag_lag{lag}"]=mag[i]; f[f"hr_lag{lag}"]=hr[i]
        for n,d in [("acc_x",ax_w),("acc_y",ay_w),("acc_z",az_w)]:
            f[f"{n}_zcr"]=float(np.sum(np.diff(d)!=0)) if len(d)>1 else 0.0
        vec=np.array([f.get(fn,0.0) for fn in feature_names],dtype=np.float32)
        return vec.reshape(1,-1)

buf = SensorBuffer()
history: deque = deque(maxlen=3600)
ws_clients: list[WebSocket] = []
mqtt_connected = False
t0 = time.time()
loop: asyncio.AbstractEventLoop = None

# ── MQTT callbacks ───────────────────────────────────────────────────────────
def on_connect(client, ud, flags, rc, props=None):
    global mqtt_connected
    if rc == 0:
        mqtt_connected = True
        client.subscribe(MQTT_TOPIC, qos=1)
        print(f"  MQTT connected -> subscribed to {MQTT_TOPIC}")
    else:
        mqtt_connected = False
        print(f"  MQTT fail rc={rc}")

def on_disconnect(client, ud, flags, rc, props=None):
    global mqtt_connected
    mqtt_connected = False
    print(f"  MQTT disconnected rc={rc}")

def on_message(client, ud, msg):
    try:
        p = json.loads(msg.payload.decode())
    except Exception:
        return
    x=float(p.get("acc_x",0)); y=float(p.get("acc_y",0))
    z=float(p.get("acc_z",0)); h=float(p.get("bpm",0))
    buf.add(x,y,z,h)
    stage="---"; conf=0.0
    fv=buf.features()
    if fv is not None:
        pi=model.predict(fv)[0]; pr=model.predict_proba(fv)[0]
        conf=float(np.max(pr)); stage=label_encoder.inverse_transform([pi])[0]
    rec={"ts":datetime.now().isoformat(),"acc_x":x,"acc_y":y,"acc_z":z,
         "hr":h,"stage":stage,"conf":round(conf,4),"n":buf.count}
    history.append(rec)
    data=json.dumps(rec)
    for ws in ws_clients[:]:
        try: asyncio.run_coroutine_threadsafe(ws.send_text(data), loop)
        except: pass

mqtt_client = mqtt.Client(client_id=f"sleepsense-{int(time.time())}",
                          protocol=mqtt.MQTTv311,
                          callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
mqtt_client.tls_set(tls_version=ssl.PROTOCOL_TLS_CLIENT)
mqtt_client.tls_insecure_set(True)
mqtt_client.username_pw_set(HIVEMQ_USER, HIVEMQ_PASS)
mqtt_client.on_connect=on_connect; mqtt_client.on_message=on_message
mqtt_client.on_disconnect=on_disconnect

def mqtt_thread():
    try: mqtt_client.connect(HIVEMQ_HOST,HIVEMQ_PORT,60); mqtt_client.loop_forever()
    except Exception as e: print(f"  MQTT error: {e}")

# ── FastAPI ──────────────────────────────────────────────────────────────────
app = FastAPI(title="SleepSense AI")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])
if DASH_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(DASH_DIR)), name="static")

@app.on_event("startup")
async def startup():
    global loop; loop=asyncio.get_event_loop()
    threading.Thread(target=mqtt_thread,daemon=True).start()
    print(f"  Dashboard -> http://localhost:8000")

@app.get("/")
async def index():
    f=DASH_DIR/"index.html"
    return FileResponse(str(f)) if f.exists() else JSONResponse({"err":"no dashboard"})

@app.get("/api/status")
async def status():
    return {"mqtt":mqtt_connected,"samples":buf.count,"ready":buf.ready,
            "predictions":len(history),"uptime":round(time.time()-t0,1),
            "accuracy":artifact["accuracy"]}

@app.get("/api/history")
async def hist(n:int=200):
    return {"records":list(history)[-n:]}

@app.websocket("/ws")
async def ws_ep(ws:WebSocket):
    await ws.accept(); ws_clients.append(ws)
    try:
        while True:
            d=await ws.receive_text()
            if d=="ping": await ws.send_text('{"type":"pong"}')
    except WebSocketDisconnect: pass
    finally:
        if ws in ws_clients: ws_clients.remove(ws)

# simulate endpoint for testing without hardware
@app.post("/api/simulate")
async def sim():
    import random
    x=random.randint(-130,130); y=random.randint(-20,20); z=random.randint(-30,30)
    h=random.uniform(55,95)
    buf.add(x,y,z,h)
    stage="---"; conf=0.0
    fv=buf.features()
    if fv is not None:
        pi=model.predict(fv)[0]; pr=model.predict_proba(fv)[0]
        conf=float(np.max(pr)); stage=label_encoder.inverse_transform([pi])[0]
    rec={"ts":datetime.now().isoformat(),"acc_x":x,"acc_y":y,"acc_z":z,
         "hr":h,"stage":stage,"conf":round(conf,4),"n":buf.count}
    history.append(rec)
    data=json.dumps(rec)
    for ws in ws_clients[:]:
        try: await ws.send_text(data)
        except: pass
    return rec

if __name__=="__main__":
    import uvicorn
    print("\n"+"="*50+"\n  SleepSense AI - Real-Time Predictor\n"+"="*50)
    uvicorn.run(app,host="0.0.0.0",port=8000,log_level="info")
