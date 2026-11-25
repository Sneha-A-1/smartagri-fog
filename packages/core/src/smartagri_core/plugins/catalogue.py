"""Catalogue of planned algorithms.

These entries are browsable in the Algorithm Catalogue with a "Planned" badge and the phase in which
they are scheduled. They have no implementation and the registry refuses to run them. When an
algorithm is implemented, its entry here is removed and replaced by a ``@register``-ed class.
"""

from smartagri_core.registry import PluginKind, declare

E, F, C = "edge", "fog", "cloud"

_SCHEDULERS = [
    ("fcfs", "First-Come, First-Served", 1, "Runs waiting tasks in arrival order."),
    ("round_robin", "Round Robin (placement)", 1, "Assigns successive tasks to nodes in cyclic order."),
    ("edf", "Earliest Deadline First", 1, "Runs the waiting task with the nearest deadline first."),
    ("least_loaded", "Least Loaded", 1, "Places each task on the node with the least queued work."),
    ("min_min", "Min-Min", 1, "Batch mapper: repeatedly assigns the task with the smallest minimum completion time."),
    (
        "cloud_only",
        "Cloud-only placement",
        1,
        "iFogSim baseline: every processing module runs in the cloud (Gupta et al., 2016).",
    ),
    (
        "edge_ward",
        "Edge-ward placement",
        1,
        "iFogSim baseline: places modules as close to the edge as capacity allows, moving toward the cloud.",
    ),
    ("sjf", "Shortest Job First", 4, "Runs the waiting task with the smallest processing length first."),
    ("priority", "Priority Scheduling", 4, "Runs tasks in order of their priority class."),
    ("max_min", "Max-Min", 4, "Batch mapper: assigns the task with the largest minimum completion time first."),
    ("heft", "HEFT", 4, "Heterogeneous Earliest Finish Time list scheduling for task DAGs."),
]

_OPTIMIZERS = [
    ("ga", "Genetic Algorithm", 4, "Evolves task-to-node mappings by selection, crossover and mutation."),
    ("pso", "Particle Swarm Optimization", 4, "Moves candidate mappings toward personal and global bests."),
    ("aco", "Ant Colony Optimization", 4, "Builds mappings guided by pheromone trails reinforced by good solutions."),
    ("gwo", "Grey Wolf Optimizer", 4, "Population metaheuristic led by the three best solutions."),
    ("woa", "Whale Optimization Algorithm", 4, "Population metaheuristic with encircling and spiral update moves."),
    ("nsga2", "NSGA-II", 4, "Multi-objective evolutionary algorithm returning a Pareto front (via pymoo)."),
    ("dqn", "Deep Q-Network", 4, "Learned scheduling policy trained in a Gymnasium environment around the simulator."),
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
