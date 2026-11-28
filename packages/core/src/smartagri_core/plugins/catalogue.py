"""Catalogue of planned algorithms (implemented baselines live in smartagri_core.sim.policies).

These entries are browsable in the Algorithm Catalogue with a "Planned" badge and the phase in which
they are scheduled. They have no implementation and the registry refuses to run them. When an
algorithm is implemented, its entry here is removed and replaced by a ``@register``-ed class.
"""

from smartagri_core.registry import PluginKind, declare

E, F, C = "edge", "fog", "cloud"

_SCHEDULERS: list[tuple[str, str, int, str]] = []  # HEFT and CPOP are implemented in smartagri_core.sched

_OPTIMIZERS = [
    ("ppo", "Proximal Policy Optimization", 4, "Policy-gradient learned scheduling policy (Stable-Baselines3)."),
]

_CLASSIFIERS = [
    ("decision_tree", "Decision Tree"),
    ("random_forest", "Random Forest"),
    ("svm", "Support Vector Machine"),
    ("knn", "K-Nearest Neighbours"),
    ("naive_bayes", "Naive Bayes"),
    ("xgboost", "XGBoost"),
    ("lightgbm", "LightGBM"),
]

_CLUSTERING = [
    ("kmeans", "K-Means"),
    ("dbscan", "DBSCAN"),
    ("hierarchical", "Hierarchical Clustering"),
    ("fuzzy_cmeans", "Fuzzy C-Means"),
]

_ANOMALY = [
    ("isolation_forest", "Isolation Forest", 3),
    ("lof", "Local Outlier Factor", 3),
    ("one_class_svm", "One-Class SVM", 3),
    ("autoencoder_anomaly", "Autoencoder", 6),
]

_DEEP = [
    ("cnn", "CNN", "Image classification, e.g. leaf disease"),
    ("resnet", "ResNet", "Image classification with residual networks"),
    ("efficientnet", "EfficientNet", "Accurate, compact image classification for edge devices"),
    ("lstm", "LSTM", "Time-series forecasting, e.g. soil moisture"),
    ("gru", "GRU", "Lighter recurrent model for time series"),
    ("transformer", "Transformer", "Attention-based time-series and sequence models"),
    ("yolo", "YOLO", "Object detection, e.g. pests in field images"),
]

for key, name, phase, summary in _SCHEDULERS:
    declare(
        kind=PluginKind.SCHEDULER, key=key, name=name, phase=phase, summary=summary, layers=[E, F, C], tags=["baseline"]
    )

for key, name, phase, summary in _OPTIMIZERS:
    declare(
        kind=PluginKind.OPTIMIZER, key=key, name=name, phase=phase, summary=summary, layers=[F, C], tags=["baseline"]
    )

for key, name in _CLASSIFIERS:
    declare(
        kind=PluginKind.CLASSIFIER,
        key=key,
        name=name,
        phase=6,
        summary=f"{name} classifier for crop, soil and health classification.",
        layers=[F, C],
    )

for key, name in _CLUSTERING:
    declare(
        kind=PluginKind.CLUSTERING,
        key=key,
        name=name,
        phase=6,
        summary=f"{name} for grouping fields, sensors or readings.",
        layers=[F, C],
    )

for key, name, phase in _ANOMALY:
    declare(
        kind=PluginKind.ANOMALY_DETECTOR,
        key=key,
        name=name,
        phase=phase,
        summary=f"{name} for detecting abnormal sensor readings.",
        layers=[E, F],
    )

for key, name, summary in _DEEP:
    declare(kind=PluginKind.DEEP_MODEL, key=key, name=name, phase=6, summary=summary + ".", layers=[E, F, C])
