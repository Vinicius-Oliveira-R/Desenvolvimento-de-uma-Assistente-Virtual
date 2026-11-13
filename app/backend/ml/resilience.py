"""Executa ML com prazo limitado e no máximo uma tarefa pendente por processo.

O timeout não mata código nativo: enquanto a tarefa terminar, novas solicitações
usam PADRAO sem criar outras threads. O worker é daemon e nunca recebe sessão SQL.
"""
import logging
import math
import threading
import time
from concurrent.futures import Future, TimeoutError
from typing import Callable

from app.backend.ml.profile_classifier import ProfilePrediction

logger = logging.getLogger(__name__)


class BoundedPredictor:
    def __init__(self):
        self._lock = threading.Lock()
        self._pending: Future | None = None
        self._retry_at = 0.0

    def call(self, fn: Callable[[], ProfilePrediction], timeout: float, retry_seconds: float) -> ProfilePrediction | None:
        with self._lock:
            if time.monotonic() < self._retry_at or (self._pending is not None and not self._pending.done()):
                return None
            future = self._pending = Future()
            def run():
                try:
                    future.set_result(fn())
                except Exception as exc:
                    future.set_exception(exc)
            threading.Thread(target=run, daemon=True, name="profile-inference").start()
        try:
            result = future.result(timeout=timeout)
            probability = result.probabilidade_idoso
            if isinstance(probability, bool) or not math.isfinite(probability) or not 0 <= probability <= 1:
                raise ValueError("invalid_prediction")
            return result
        except TimeoutError:
            logger.warning("ML indisponível: timeout; fallback=PADRAO")
        except Exception as exc:
            with self._lock:
                self._retry_at = time.monotonic() + retry_seconds
            logger.warning("ML indisponível: causa=%s; fallback=PADRAO", type(exc).__name__)
        return None


predictor = BoundedPredictor()
