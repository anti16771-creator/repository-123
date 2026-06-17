# PredictX — 반도체 장비 예지보전 시스템

## 아키텍처

```
predictx/
├── backend/
│   ├── main.py               # FastAPI 서버 (REST + WebSocket)
│   ├── sensor_simulator.py   # 센서 데이터 소스 (시뮬 → 실제 교체 가능)
│   ├── anomaly_detector.py   # AI 이상 탐지 (IF + LSTM Autoencoder)
│   └── requirements.txt
└── frontend/
    └── index.html            # 실시간 대시보드 (WebSocket 연동)
```

## 빠른 시작

### 1. 백엔드 설치 및 실행

```bash
cd backend
pip install -r requirements.txt
python main.py
# → http://localhost:8000 에서 서버 실행
# → API 문서: http://localhost:8000/docs
```

### 2. 프론트엔드 열기

```bash
# 방법 A: 브라우저에서 frontend/index.html 직접 열기
# 방법 B: 백엔드가 /frontend 폴더를 자동 서빙 → http://localhost:8000
```

---

## AI 모델 상세

### Isolation Forest (즉시 탐지)
- 학습 시작: 100개 샘플 수집 후 자동 학습
- 재학습: 200개마다 자동 갱신
- 탐지 방식: 단일 포인트 이상값 탐지
- 특징: 빠름, 메모리 적음, 초기부터 동작

### LSTM Autoencoder (패턴 탐지)
- 학습 시작: 약 130개 샘플 (30개 시퀀스 × 여유분) 후
- 재학습: 500 업데이트마다 자동 갱신
- 탐지 방식: 30초 시계열 패턴 재구성 오차
- 특징: 정확함, 복합 패턴 탐지 가능

### 앙상블 (기본 운영 모드)
- 두 모델 준비 완료 시 자동 전환
- 가중치: IF 40% + LSTM 60%
- 임계값: 앙상블 스코어 0.5 이상 → 이상 판정

---

## REST API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | /health | 서버 상태 확인 |
| GET | /api/model/status | AI 모델 학습 현황 |
| GET | /api/sensors/latest | 전체 장비 최신 센서값 |
| GET | /api/sensors/{id}/history | 장비별 이력 (n=60 기본) |
| GET | /api/alerts | AI 탐지 알림 목록 |
| GET | /api/equipment | 장비 목록 + AI 준비 상태 |
| WS  | /ws/stream | 실시간 센서 + AI 결과 스트림 |

---

## 실제 센서 연동 방법

`sensor_simulator.py`의 `SensorHub` 클래스만 교체하면 됩니다.

### MQTT 연동 예시
```python
import paho.mqtt.client as mqtt

class MQTTSensorHub(SensorHub):
    def __init__(self, broker_host, broker_port=1883):
        super().__init__()
        self.client = mqtt.Client()
        self.client.on_message = self._on_message
        self.client.connect(broker_host, broker_port)
        self.client.subscribe("sensors/#")
        self.client.loop_start()

    def _on_message(self, client, userdata, msg):
        data = json.loads(msg.payload)
        reading = SensorReading(**data)
        self._history[reading.equipment_id].append(reading)

    def tick_all(self):
        # MQTT는 push 방식이므로 최신값 반환
        return [self.get_latest(id) for id in self.EQUIPMENT_IDS if self.get_latest(id)]
```

### OPC-UA 연동 예시
```python
from asyncua import Client as OPCClient

class OPCUASensorHub(SensorHub):
    async def connect(self, endpoint_url):
        self.opc = OPCClient(url=endpoint_url)
        await self.opc.connect()
        # 노드 구독 설정...
```

---

## 배포 (선택)

### Docker
```bash
# Dockerfile 예시
FROM python:3.11-slim
WORKDIR /app
COPY backend/ .
RUN pip install -r requirements.txt
EXPOSE 8000
CMD ["python", "main.py"]
```

### 클라우드 배포
- **Railway / Render**: GitHub 연결 후 자동 배포
- **AWS EC2 / GCP Compute**: `uvicorn main:app --host 0.0.0.0 --port 8000`
- 배포 후 `frontend/index.html`의 `API_BASE`와 `WS_URL`을 실제 서버 주소로 변경
