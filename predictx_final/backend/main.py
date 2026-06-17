"""
main.py  —  PredictX FastAPI 서버
Railway / Render 클라우드 배포 대응 (PORT 환경변수 자동 처리)
"""
import asyncio
import json
import os
import time
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from sensor_simulator import SensorHub
from anomaly_detector import DetectorHub

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

sensor_hub   = SensorHub()
detector_hub = DetectorHub(SensorHub.EQUIPMENT_IDS)
ws_clients: set[WebSocket] = set()
recent_alerts: list[dict] = []
MAX_ALERTS = 100


async def streaming_loop():
    global recent_alerts
    while True:
        readings = sensor_hub.tick_all()
        payload_items = []
        for reading in readings:
            result = detector_hub.update(reading)
            item = {
                "equipment_id": reading.equipment_id,
                "timestamp":    reading.timestamp,
                "sensors": {
                    "temperature": reading.temperature,
                    "vibration":   reading.vibration,
                    "pressure":    reading.pressure,
                    "current":     reading.current,
                    "humidity":    reading.humidity,
                },
                "anomaly": None,
            }
            if result:
                item["anomaly"] = {
                    "is_anomaly":           result.is_anomaly,
                    "score":                result.score,
                    "confidence":           result.confidence,
                    "method":               result.method,
                    "reconstruction_error": result.reconstruction_error,
                    "if_score":             result.if_score,
                    "details":              result.details,
                }
                if result.is_anomaly:
                    recent_alerts.append({
                        "equipment_id": reading.equipment_id,
                        "timestamp":    reading.timestamp,
                        "score":        result.score,
                        "method":       result.method,
                        "details":      result.details,
                    })
                    if len(recent_alerts) > MAX_ALERTS:
                        recent_alerts = recent_alerts[-MAX_ALERTS:]
            payload_items.append(item)

        if ws_clients:
            msg = json.dumps({"type": "sensor_batch", "data": payload_items})
            dead = set()
            for ws in ws_clients:
                try:
                    await ws.send_text(msg)
                except Exception:
                    dead.add(ws)
            ws_clients -= dead

        await asyncio.sleep(1.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(streaming_loop())
    logger.info("PredictX 스트리밍 루프 시작")
    yield
    task.cancel()


app = FastAPI(title="PredictX API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.websocket("/ws/stream")
async def ws_stream(websocket: WebSocket):
    await websocket.accept()
    ws_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_clients.discard(websocket)


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": time.time(), "ws_clients": len(ws_clients)}


@app.get("/api/model/status")
def model_status():
    return {"models": detector_hub.get_status()}


@app.get("/api/sensors/latest")
def sensors_latest():
    result = []
    for eq_id in SensorHub.EQUIPMENT_IDS:
        r = sensor_hub.get_latest(eq_id)
        if r:
            result.append({"equipment_id": r.equipment_id, "timestamp": r.timestamp,
                "temperature": r.temperature, "vibration": r.vibration,
                "pressure": r.pressure, "current": r.current, "humidity": r.humidity})
    return result


@app.get("/api/sensors/{equipment_id}/history")
def sensor_history(equipment_id: str, n: int = 60):
    if equipment_id not in SensorHub.EQUIPMENT_IDS:
        raise HTTPException(status_code=404, detail=f"장비 {equipment_id} 없음")
    return [{"timestamp": r.timestamp, "temperature": r.temperature, "vibration": r.vibration,
             "pressure": r.pressure, "current": r.current, "humidity": r.humidity}
            for r in sensor_hub.get_history(equipment_id, n)]


@app.get("/api/alerts")
def get_alerts(equipment_id: Optional[str] = None, n: int = 50):
    return [{"equipment_id": a.equipment_id, "timestamp": a.timestamp, "score": a.score,
             "confidence": a.confidence, "method": a.method,
             "reconstruction_error": a.reconstruction_error,
             "if_score": a.if_score, "details": a.details}
            for a in detector_hub.get_alerts(equipment_id, n)]


@app.get("/api/equipment")
def equipment_list():
    status_map = {s["equipment_id"]: s for s in detector_hub.get_status()}
    result = []
    for eq_id in SensorHub.EQUIPMENT_IDS:
        r  = sensor_hub.get_latest(eq_id)
        st = status_map.get(eq_id, {})
        result.append({"equipment_id": eq_id,
            "ai_ready":    st.get("if_trained", False) or st.get("lstm_trained", False),
            "alert_count": st.get("alert_count", 0),
            "latest_temp": r.temperature if r else None,
            "latest_vib":  r.vibration   if r else None})
    return result


# 프론트엔드 서빙 (Docker: /app/frontend, 로컬: ../frontend)
_base = os.path.dirname(__file__)
for _fp in [os.path.join(_base, "..", "frontend"), os.path.join(_base, "frontend")]:
    if os.path.isdir(_fp):
        app.mount("/", StaticFiles(directory=_fp, html=True), name="static")
        logger.info(f"프론트엔드 서빙: {_fp}")
        break


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
