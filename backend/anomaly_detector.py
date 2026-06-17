"""
anomaly_detector.py
Isolation Forest (실시간 빠른 탐지) + LSTM Autoencoder (시계열 패턴 정밀 탐지) 앙상블
"""
import numpy as np
import logging
from dataclasses import dataclass
from typing import Optional
from collections import deque

logger = logging.getLogger(__name__)

# ── 공통 피처 순서 ──────────────────────────────────────────────
FEATURES = ["temperature", "vibration", "pressure", "current", "humidity"]

@dataclass
class AnomalyResult:
    equipment_id: str
    timestamp: float
    is_anomaly: bool
    score: float            # 0~1, 높을수록 이상
    confidence: float       # 0~1
    method: str             # "isolation_forest" | "lstm_ae" | "ensemble"
    reconstruction_error: Optional[float] = None
    if_score: Optional[float] = None
    details: str = ""


# ══════════════════════════════════════════════════════════════════
# 1. Isolation Forest — 실시간 단일 포인트 탐지
# ══════════════════════════════════════════════════════════════════
class IsolationForestDetector:
    """
    sklearn IsolationForest 래퍼.
    MIN_TRAIN_SAMPLES개 누적 후 자동 학습, 이후 스트리밍 추론.
    """
    MIN_TRAIN_SAMPLES = 100
    RETRAIN_INTERVAL  = 200   # N 샘플마다 재학습

    def __init__(self, contamination: float = 0.05):
        self.contamination = contamination
        self._model = None
        self._scaler = None
        self._buffer: list[list[float]] = []
        self._sample_count = 0
        self._trained = False

    def _extract(self, reading) -> list[float]:
        return [getattr(reading, f) for f in FEATURES]

    def _fit(self):
        from sklearn.ensemble import IsolationForest
        from sklearn.preprocessing import StandardScaler
        X = np.array(self._buffer)
        self._scaler = StandardScaler().fit(X)
        Xs = self._scaler.transform(X)
        self._model = IsolationForest(
            n_estimators=150,
            contamination=self.contamination,
            random_state=42,
            n_jobs=-1,
        ).fit(Xs)
        self._trained = True
        logger.info(f"IsolationForest 학습 완료 — {len(self._buffer)}샘플")

    def update(self, reading) -> Optional[AnomalyResult]:
        vec = self._extract(reading)
        self._buffer.append(vec)
        self._sample_count += 1

        # 버퍼 크기 제한
        if len(self._buffer) > 2000:
            self._buffer = self._buffer[-1000:]

        # 초기 학습 또는 주기적 재학습
        if (self._sample_count == self.MIN_TRAIN_SAMPLES or
                (self._trained and self._sample_count % self.RETRAIN_INTERVAL == 0)):
            self._fit()

        if not self._trained:
            return None  # 학습 전엔 결과 없음

        Xs = self._scaler.transform([vec])
        raw_score = self._model.score_samples(Xs)[0]   # 음수, 낮을수록 이상
        pred = self._model.predict(Xs)[0]              # -1=이상, 1=정상

        # 0~1 정규화 (score_samples 범위는 대략 -0.8 ~ 0.1)
        normalized = float(np.clip((raw_score + 0.8) / 0.9, 0, 1))
        anomaly_score = 1.0 - normalized

        return AnomalyResult(
            equipment_id=reading.equipment_id,
            timestamp=reading.timestamp,
            is_anomaly=(pred == -1),
            score=round(anomaly_score, 4),
            confidence=round(abs(anomaly_score - 0.5) * 2, 4),
            method="isolation_forest",
            if_score=round(float(raw_score), 4),
        )


# ══════════════════════════════════════════════════════════════════
# 2. LSTM Autoencoder — 시계열 패턴 기반 정밀 탐지
# ══════════════════════════════════════════════════════════════════
class LSTMAutoencoderDetector:
    """
    LSTM Autoencoder: 정상 패턴을 학습해 재구성 오차로 이상 탐지.
    시퀀스 길이(SEQ_LEN) 구간의 패턴 이탈을 포착.
    """
    SEQ_LEN          = 30    # 30포인트(=30초) 시퀀스
    MIN_TRAIN_SEQ    = 80    # 최소 학습 시퀀스 수
    LATENT_DIM       = 16
    THRESHOLD_PCTILE = 95    # 정상 재구성 오차의 95퍼센타일을 임계값으로

    def __init__(self):
        self._model = None
        self._scaler = None
        self._window: deque = deque(maxlen=self.SEQ_LEN)
        self._train_errors: list[float] = []
        self._threshold: Optional[float] = None
        self._trained = False
        self._train_buffer: list[list[float]] = []
        self._n_updates = 0

    def _extract(self, reading) -> list[float]:
        return [getattr(reading, f) for f in FEATURES]

    def _build_model(self, n_features: int):
        """TensorFlow가 없으면 NumPy 기반 간이 AE로 폴백"""
        try:
            import tensorflow as tf
            from tensorflow import keras
            n_in = self.SEQ_LEN * n_features

            inp = keras.Input(shape=(self.SEQ_LEN, n_features))
            # Encoder
            x = keras.layers.LSTM(32, return_sequences=True)(inp)
            x = keras.layers.LSTM(self.LATENT_DIM, return_sequences=False)(x)
            # Decoder
            x = keras.layers.RepeatVector(self.SEQ_LEN)(x)
            x = keras.layers.LSTM(self.LATENT_DIM, return_sequences=True)(x)
            x = keras.layers.LSTM(32, return_sequences=True)(x)
            out = keras.layers.TimeDistributed(keras.layers.Dense(n_features))(x)

            model = keras.Model(inp, out)
            model.compile(optimizer="adam", loss="mse")
            self._use_tf = True
            logger.info("LSTM Autoencoder (TensorFlow) 모델 생성")
            return model
        except ImportError:
            logger.warning("TensorFlow 없음 — NumPy PCA 기반 AE로 폴백")
            self._use_tf = False
            return None

    def _fit(self, sequences: np.ndarray):
        n_features = sequences.shape[2]

        if self._model is None:
            self._model = self._build_model(n_features)

        if self._use_tf:
            self._model.fit(
                sequences, sequences,
                epochs=15, batch_size=32,
                validation_split=0.1,
                verbose=0,
            )
            preds = self._model.predict(sequences, verbose=0)
            errors = np.mean(np.square(sequences - preds), axis=(1, 2))
        else:
            # 폴백: PCA 기반 재구성 오차
            flat = sequences.reshape(len(sequences), -1)
            from sklearn.decomposition import PCA
            pca = PCA(n_components=min(self.LATENT_DIM, flat.shape[1]))
            encoded = pca.fit_transform(flat)
            decoded = pca.inverse_transform(encoded)
            errors = np.mean(np.square(flat - decoded), axis=1)
            self._pca = pca

        self._threshold = float(np.percentile(errors, self.THRESHOLD_PCTILE))
        self._train_errors = errors.tolist()
        self._trained = True
        logger.info(f"LSTM AE 학습 완료 — {len(sequences)}시퀀스, 임계값={self._threshold:.4f}")

    def _make_sequences(self, data: list[list[float]]) -> np.ndarray:
        from sklearn.preprocessing import MinMaxScaler
        arr = np.array(data)
        if self._scaler is None:
            self._scaler = MinMaxScaler()
            arr = self._scaler.fit_transform(arr)
        else:
            arr = self._scaler.transform(arr)
        seqs = []
        for i in range(len(arr) - self.SEQ_LEN + 1):
            seqs.append(arr[i:i+self.SEQ_LEN])
        return np.array(seqs)

    def update(self, reading) -> Optional[AnomalyResult]:
        vec = self._extract(reading)
        self._window.append(vec)
        self._train_buffer.append(vec)
        self._n_updates += 1

        # 최소 시퀀스 확보 후 최초 학습
        needed = (self.MIN_TRAIN_SEQ + self.SEQ_LEN - 1)
        if not self._trained and len(self._train_buffer) >= needed:
            seqs = self._make_sequences(self._train_buffer)
            self._fit(seqs)

        # 주기적 재학습 (500 업데이트마다)
        elif self._trained and self._n_updates % 500 == 0:
            recent = self._train_buffer[-1000:]
            seqs = self._make_sequences(recent)
            if len(seqs) > 10:
                self._fit(seqs)

        if not self._trained or len(self._window) < self.SEQ_LEN:
            return None

        # 현재 윈도우 추론
        arr = np.array(list(self._window))
        arr_scaled = self._scaler.transform(arr)
        seq = arr_scaled[np.newaxis, ...]   # (1, SEQ_LEN, n_features)

        if self._use_tf:
            pred = self._model.predict(seq, verbose=0)
        else:
            flat = seq.reshape(1, -1)
            decoded = self._pca.inverse_transform(self._pca.transform(flat))
            pred = decoded.reshape(seq.shape)

        error = float(np.mean(np.square(seq - pred)))
        is_anomaly = error > self._threshold
        # 0~1 정규화
        score = float(np.clip(error / (self._threshold * 3), 0, 1))

        return AnomalyResult(
            equipment_id=reading.equipment_id,
            timestamp=reading.timestamp,
            is_anomaly=is_anomaly,
            score=round(score, 4),
            confidence=round(abs(score - 0.5) * 2, 4),
            method="lstm_ae",
            reconstruction_error=round(error, 6),
        )


# ══════════════════════════════════════════════════════════════════
# 3. Ensemble — 두 모델 결합
# ══════════════════════════════════════════════════════════════════
class EnsembleDetector:
    """
    IF + LSTM AE 앙상블.
    - 두 모델 모두 학습 완료: 가중 평균 (IF 0.4 + LSTM 0.6)
    - 한 모델만 준비됨: 단독 사용
    """
    IF_WEIGHT   = 0.4
    LSTM_WEIGHT = 0.6
    THRESHOLD   = 0.5

    def __init__(self, equipment_id: str):
        self.equipment_id = equipment_id
        self.if_detector   = IsolationForestDetector()
        self.lstm_detector = LSTMAutoencoderDetector()
        self.alert_history: list[AnomalyResult] = []

    def update(self, reading) -> Optional[AnomalyResult]:
        if_result   = self.if_detector.update(reading)
        lstm_result = self.lstm_detector.update(reading)

        # 두 모델 모두 미준비
        if if_result is None and lstm_result is None:
            return None

        # 한 모델만 준비됨
        if if_result is None:
            result = lstm_result
        elif lstm_result is None:
            result = if_result
        else:
            # 앙상블
            ensemble_score = (
                self.IF_WEIGHT   * if_result.score +
                self.LSTM_WEIGHT * lstm_result.score
            )
            is_anomaly = ensemble_score >= self.THRESHOLD
            result = AnomalyResult(
                equipment_id=reading.equipment_id,
                timestamp=reading.timestamp,
                is_anomaly=is_anomaly,
                score=round(ensemble_score, 4),
                confidence=round(abs(ensemble_score - 0.5) * 2, 4),
                method="ensemble",
                reconstruction_error=lstm_result.reconstruction_error,
                if_score=if_result.if_score,
                details=f"IF={if_result.score:.3f} LSTM={lstm_result.score:.3f}",
            )

        if result and result.is_anomaly:
            self.alert_history.append(result)
            if len(self.alert_history) > 200:
                self.alert_history = self.alert_history[-100:]

        return result

    @property
    def is_ready(self) -> bool:
        return self.if_detector._trained or self.lstm_detector._trained

    @property
    def status(self) -> dict:
        return {
            "equipment_id": self.equipment_id,
            "if_trained":   self.if_detector._trained,
            "lstm_trained": self.lstm_detector._trained,
            "if_samples":   len(self.if_detector._buffer),
            "lstm_seqs":    max(0, len(self.lstm_detector._train_buffer) - self.lstm_detector.SEQ_LEN + 1),
            "alert_count":  len(self.alert_history),
        }


# ══════════════════════════════════════════════════════════════════
# 4. DetectorHub — 장비별 Detector 관리
# ══════════════════════════════════════════════════════════════════
class DetectorHub:
    def __init__(self, equipment_ids: list[str]):
        self.detectors: dict[str, EnsembleDetector] = {
            eq_id: EnsembleDetector(eq_id) for eq_id in equipment_ids
        }

    def update(self, reading) -> Optional[AnomalyResult]:
        det = self.detectors.get(reading.equipment_id)
        if det is None:
            return None
        return det.update(reading)

    def get_status(self) -> list[dict]:
        return [d.status for d in self.detectors.values()]

    def get_alerts(self, equipment_id: Optional[str] = None, n: int = 50) -> list[AnomalyResult]:
        if equipment_id:
            det = self.detectors.get(equipment_id)
            return det.alert_history[-n:] if det else []
        all_alerts = []
        for d in self.detectors.values():
            all_alerts.extend(d.alert_history)
        return sorted(all_alerts, key=lambda a: a.timestamp, reverse=True)[:n]
