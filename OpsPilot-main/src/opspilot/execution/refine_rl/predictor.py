"""Pre-Refinement Predictor: predicts a per-module starting iteration budget
from Discovery-time features, trained on logged historical (features -> actual
iteration count) pairs, per the idea write-up.

Uses a small gradient-boosted regressor (scikit-learn) by default -- exactly
the "small regression/classification model (scikit-learn), trivial to train and
cheap to run per module" the write-up specifies -- with a plain-numpy linear
regression fallback so this subsystem still functions in an environment where
scikit-learn is unavailable (consistent with the base repo's general "no hard
external-service dependency" ethos, e.g. the offline `autogen` shim).
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import numpy as np

from opspilot.execution.refine_rl.module_features import ModuleFeatures

try:
    from sklearn.ensemble import GradientBoostingRegressor
    _SKLEARN_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without sklearn installed
    _SKLEARN_AVAILABLE = False


class _LinearFallbackRegressor:
    """Minimal closed-form ridge regression fallback (no external dependency)."""

    def __init__(self, ridge: float = 1.0):
        self.ridge = ridge
        self.weights: Optional[np.ndarray] = None

    def fit(self, X: np.ndarray, y: np.ndarray):
        X_aug = np.hstack([X, np.ones((X.shape[0], 1))])
        d = X_aug.shape[1]
        self.weights = np.linalg.solve(X_aug.T @ X_aug + self.ridge * np.eye(d), X_aug.T @ y)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        X_aug = np.hstack([X, np.ones((X.shape[0], 1))])
        return X_aug @ self.weights


class IterationBudgetPredictor:
    """Predicts a starting iteration budget for a module from its static
    features. Falls back to a fixed heuristic (the survey's own reported
    3-5 / 12 split) until enough training data has been logged."""

    MIN_TRAINING_SAMPLES = 20

    def __init__(self, use_sklearn: Optional[bool] = None, min_budget: int = 2, max_budget: int = 15):
        self.use_sklearn = _SKLEARN_AVAILABLE if use_sklearn is None else (use_sklearn and _SKLEARN_AVAILABLE)
        self.model = None
        self.min_budget = min_budget
        self.max_budget = max_budget
        self._trained = False

    def _heuristic_predict(self, features: ModuleFeatures) -> int:
        """Fallback used pre-training: mirrors the survey's own reported
        3-5 (well-structured) vs up to 12 (embedded SQL/CICS) split (Sec. VI)."""
        budget = 4
        if features.embedded_sql:
            budget += 4
        if features.cics_handler:
            budget += 4
        if features.cyclomatic_complexity > 15:
            budget += 2
        return int(np.clip(budget, self.min_budget, self.max_budget))

    def fit(self, features_list: List[ModuleFeatures], actual_iterations: List[int]):
        if len(features_list) < self.MIN_TRAINING_SAMPLES:
            self._trained = False
            return self

        X = np.array([f.to_vector() for f in features_list])
        y = np.array(actual_iterations, dtype=float)

        if self.use_sklearn:
            self.model = GradientBoostingRegressor(n_estimators=80, max_depth=2, learning_rate=0.08, random_state=0)
        else:
            self.model = _LinearFallbackRegressor(ridge=2.0)
        self.model.fit(X, y)
        self._trained = True
        return self

    def predict(self, features: ModuleFeatures) -> int:
        if not self._trained or self.model is None:
            return self._heuristic_predict(features)
        pred = float(self.model.predict(np.array([features.to_vector()]))[0])
        return int(np.clip(round(pred), self.min_budget, self.max_budget))

    @property
    def is_trained(self) -> bool:
        return self._trained
