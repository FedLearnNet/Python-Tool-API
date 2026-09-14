"""Canonical metric-name contract shared between apps and the global backend.

The set of metric names an app emits via ``send_metric`` is a *contract*: the global-learning-api
parses exactly these names to build the federated evaluation summary (the "Evaluation" tab). Passing
raw strings on both ends invites silent drift — a typo emits a metric nobody reads. Using this enum in
the app makes the contract explicit and greppable.

This enum is intentionally mirrored by the Java enum
``de.unihamburg.daibetes.api.project.experiment.federated.metrics.EvaluationMetric`` (and
``SiteDescriptor``) in the global backend. The two live in separate codebases and are *offset*
duplicates by necessity — keep their string values in lock-step when changing either side. See the
"Metric contract" page in the tool-developer documentation.
"""
from __future__ import annotations

from enum import Enum

#: Prefix used for the standalone institution-local baseline counterpart of a ``val_*`` metric.
LOCAL_PREFIX = "local_"


class MetricName(str, Enum):
    """Every metric name the global evaluation pipeline understands.

    Inherits from ``str`` so an instance is accepted anywhere a metric-name string is expected
    (``send_metric(MetricName.VAL_AUC, ...)`` works directly and serialises to ``"val_auc"``).
    """

    # --- Validation performance (the selectable evaluation metrics; primary first) -------------
    VAL_AUC = "val_auc"
    VAL_AUPRC = "val_auprc"
    VAL_F1 = "val_f1"
    VAL_PRECISION = "val_precision"
    VAL_RECALL = "val_recall"
    VAL_ACCURACY = "val_accuracy"
    VAL_BRIER = "val_brier"

    # --- Training performance (generalization-gap context) -------------------------------------
    TRAIN_AUC = "train_auc"
    TRAIN_AUPRC = "train_auprc"
    TRAIN_ACCURACY = "train_accuracy"

    # --- Cohort descriptors (privacy-safe counts; see secure_count) ----------------------------
    N_SAMPLES_TRAIN = "n_samples_train"
    N_SAMPLES_VAL = "n_samples_val"
    N_FEATURES = "n_features"
    VAL_POSITIVE_RATE = "val_positive_rate"

    # --- Scalability / communication (operational dimension D4) --------------------------------
    ROUND_SECONDS = "round_seconds"   # wall-clock for the full round
    COMM_SECONDS = "comm_seconds"     # wall-clock spent in the aggregate() round-trip
    N_PARAMS = "n_params"             # model parameters exchanged per round (payload size proxy)

    def local(self) -> str:
        """Name of this metric's standalone-local-baseline counterpart (e.g. ``local_val_auc``)."""
        return LOCAL_PREFIX + self.value


#: The ``val_*`` metrics offered in the evaluation UI toggle, primary endpoint first. Mirrors the Java
#: ``EvaluationMetric`` order so the backend and app agree on what is computed and selectable.
EVAL_METRICS: list[MetricName] = [
    MetricName.VAL_AUC,
    MetricName.VAL_AUPRC,
    MetricName.VAL_F1,
    MetricName.VAL_PRECISION,
    MetricName.VAL_RECALL,
    MetricName.VAL_ACCURACY,
    MetricName.VAL_BRIER,
]

#: Primary endpoint used for convergence and headline figures.
PRIMARY_METRIC: MetricName = MetricName.VAL_AUC
