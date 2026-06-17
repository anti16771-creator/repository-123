"""
sensor_simulator.py
실제 환경에서는 이 파일만 교체하면 MQTT / OPC-UA / REST 연동 가능
"""
import asyncio
import random
import math
import time
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class SensorReading:
    equipment_id: str
    timestamp: float
    temperature: float      # °C
    vibration: float        # mm/s
    pressure: float         # mTorr
    current: float          # A
    humidity: float         # %RH
    is_anomaly: bool = False
    anomaly_score: float = 0.0
    anomaly_type: Optional[str] = None

class EquipmentSimulator:
    """
    장비 1대의 정상 / 이상 상태를 시뮬레이션.
    실제 장비 연동 시 이 클래스를 MQTT 클라이언트나 OPC-UA 노드로 교체.
    """
    FAULT_MODES = ["overheat", "vibration", "pressure_drop", "power_spike", None]

    def __init__(self, equipment_id: str, fault_probability: float = 0.05):
        self.equipment_id = equipment_id
        self.fault_probability = fault_probability
        self.current_fault: Optional[str] = None
        self.fault_step: int = 0
        self._t = 0  # 내부 시간 카운터 (노이즈 주기용)

        # 장비별 기준값 약간씩 다르게
        seed = sum(ord(c) for c in equipment_id)
        rng = random.Random(seed)
        self.base = {
            "temperature": rng.uniform(260, 290),
            "vibration":   rng.uniform(1.2, 2.0),
            "pressure":    rng.uniform(55, 70),
            "current":     rng.uniform(40, 55),
            "humidity":    rng.uniform(40, 60),
        }

    def _noise(self, scale: float = 1.0) -> float:
        return random.gauss(0, scale)

    def _sine(self, period: float = 30.0, amp: float = 1.0) -> float:
        return amp * math.sin(2 * math.pi * self._t / period)

    def tick(self) -> SensorReading:
        self._t += 1

        # 고장 발생 여부 결정
        if self.current_fault is None and random.random() < self.fault_probability:
            self.current_fault = random.choice([m for m in self.FAULT_MODES if m])
            self.fault_step = 0

        # 센서값 계산
        temp = self.base["temperature"] + self._sine(40, 3) + self._noise(1.5)
        vib  = self.base["vibration"]   + self._sine(20, 0.2) + self._noise(0.1)
        pres = self.base["pressure"]    + self._sine(60, 2) + self._noise(0.8)
        curr = self.base["current"]     + self._sine(50, 1.5) + self._noise(0.5)
        humi = self.base["humidity"]    + self._noise(0.3)

        is_anomaly = False
        anomaly_type = None

        # 고장 모드별 센서 왜곡
        if self.current_fault:
            self.fault_step += 1
            ramp = min(1.0, self.fault_step / 20)  # 20틱에 걸쳐 점진적 악화

            if self.current_fault == "overheat":
                temp += ramp * 40
                curr += ramp * 8
            elif self.current_fault == "vibration":
                vib  += ramp * 5
                temp += ramp * 10
            elif self.current_fault == "pressure_drop":
                pres -= ramp * 25
                vib  += ramp * 1.5
            elif self.current_fault == "power_spike":
                curr += ramp * 20 + self._noise(3)
                temp += ramp * 15

            if ramp > 0.4:
                is_anomaly = True
                anomaly_type = self.current_fault

            # 40틱 후 자동 복구 (정비 완료 시뮬)
            if self.fault_step >= 40:
                self.current_fault = None
                self.fault_step = 0

        return SensorReading(
            equipment_id=self.equipment_id,
            timestamp=time.time(),
            temperature=round(temp, 2),
            vibration=round(max(0, vib), 3),
            pressure=round(max(0, pres), 2),
            current=round(max(0, curr), 2),
            humidity=round(min(100, max(0, humi)), 1),
            is_anomaly=is_anomaly,
            anomaly_type=anomaly_type,
        )


class SensorHub:
    """
    여러 장비를 관리하는 허브.
    MQTT 브로커 연결 시: __init__에서 mqtt.Client() 초기화, tick()을 on_message 콜백으로 교체.
    OPC-UA 연결 시: asyncua.Client()로 교체.
    """
    EQUIPMENT_IDS = ["CVD-01", "CVD-02", "CMP-01", "ETH-01", "IMP-01", "LIT-01"]
    FAULT_PROBS   = [0.08,     0.03,     0.04,     0.06,     0.12,     0.02]

    def __init__(self):
        self.simulators = {
            eq_id: EquipmentSimulator(eq_id, fp)
            for eq_id, fp in zip(self.EQUIPMENT_IDS, self.FAULT_PROBS)
        }
        self._history: dict[str, list[SensorReading]] = {e: [] for e in self.EQUIPMENT_IDS}
        self.MAX_HISTORY = 500

    def tick_all(self) -> list[SensorReading]:
        readings = []
        for eq_id, sim in self.simulators.items():
            r = sim.tick()
            self._history[eq_id].append(r)
            if len(self._history[eq_id]) > self.MAX_HISTORY:
                self._history[eq_id].pop(0)
            readings.append(r)
        return readings

    def get_history(self, equipment_id: str, n: int = 100) -> list[SensorReading]:
        return self._history.get(equipment_id, [])[-n:]

    def get_latest(self, equipment_id: str) -> Optional[SensorReading]:
        h = self._history.get(equipment_id, [])
        return h[-1] if h else None
