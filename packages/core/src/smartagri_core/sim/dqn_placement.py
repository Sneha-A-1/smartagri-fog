"""DQN placement: a learned online scheduler, trained in the simulator on workloads it is not tested on.

**Decision.** When a task arrives, the policy scores every eligible node with the Q-network and sends the task
to the highest-scoring one (during training, a random node with probability epsilon).

**Features** of a (task, node) pair, all scale-free: estimated finish time relative to the time left before
the deadline, whether that estimate meets the deadline, upload time and queue wait relative to that time, the
node's free cores, its layer (edge, fog, cloud), its energy and cost for this task relative to the most
expensive candidate, the finish-time rank among candidates, the task's priority weight and its deadline.

**Reward** of a decision, known once the task has finished: +w if the deadline was met and -w otherwise
(w is the priority weight: critical 4, high 2, medium 1, low 0.5), minus ``lambda_energy`` times the relative
energy and ``lambda_cost`` times the relative cost of the chosen node. The next state is the next decision.

**Training.** Each episode simulates ``episode_s`` seconds of a fresh workload drawn from the same generator as
the evaluation, with seeds ``train_seed + episode``, far away from the small seeds experiments use, so the
policy is never tested on a workload it trained on. Rewards are computed when the episode ends; then the agent
makes ``updates_per_episode`` gradient steps on its replay buffer. Epsilon falls linearly from
``epsilon_start`` to ``epsilon_end``. Training is deterministic for given parameters, and a trained policy is
cached per (network, workload generator, settings, parameters) so repeated replications reuse it.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from smartagri_core.progress import ProgressReporter, null_progress
from smartagri_core.registry import PluginKind, get_registry, register
from smartagri_core.sched.batchopt import PRIORITY_WEIGHT
from smartagri_core.sched.dqn import DQNAgent, DQNConfig
from smartagri_core.sim.engine import SimSettings, simulate
from smartagri_core.sim.metrics import compute_metrics
from smartagri_core.sim.opt_benchmark import _clean
from smartagri_core.sim.policies import ALL_LAYERS, ClusterView, Placement
from smartagri_core.sim.runner import ScenarioParams, _environment
from smartagri_core.sim.topology import Layer, Topology
from smartagri_core.sim.workload import Task, WorkloadSpec, generate_trace
from smartagri_core.stats import compare, summarize
from smartagri_core.status import CapabilityStatus, DataOrigin

IMPL = CapabilityStatus.IMPLEMENTED
FEATURES = [
    "finish_over_slack",
    "meets_deadline",
    "upload_over_slack",
    "wait_over_slack",
    "free_core_share",
    "layer_edge",
    "layer_fog",
    "layer_cloud",
    "energy_relative",
    "cost_relative",
    "finish_rank",
    "priority_weight",
    "log_deadline",
]


def candidate_features(task: Task, view: ClusterView) -> tuple[list[str], np.ndarray]:
    """Feature matrix (one row per eligible node) for one decision."""
    nodes = view.eligible(task)
    if not nodes:
        return [], np.zeros((0, len(FEATURES)))
    now = view.now
    slack = max(task.abs_deadline - now, 1e-3)
    est = np.array([view.estimate_finish(task, n.id) - now for n in nodes])
    up = np.array([view.transfer_time(task.source, n.id, task.input_bytes) for n in nodes])
    wait = np.array([view.backlog_s(n.id) for n in nodes])
    exe = np.array([task.length_mi / n.mips for n in nodes])
    energy = np.array([(n.p_max_w - n.p_idle_w) / n.cores for n in nodes]) * exe
    cost = np.array([n.cost_per_core_s for n in nodes]) * exe
    spread = est.max() - est.min()
    x = np.empty((len(nodes), len(FEATURES)))
    x[:, 0] = np.clip(est / slack, 0.0, 5.0)
    x[:, 1] = est <= slack
    x[:, 2] = np.clip(up / slack, 0.0, 5.0)
    x[:, 3] = np.clip(wait / slack, 0.0, 5.0)
    x[:, 4] = [view.free_cores(n.id) / n.cores for n in nodes]
    x[:, 5] = [n.layer == Layer.EDGE for n in nodes]
    x[:, 6] = [n.layer == Layer.FOG for n in nodes]
    x[:, 7] = [n.layer == Layer.CLOUD for n in nodes]
    x[:, 8] = energy / energy.max() if energy.max() > 0 else 0.0
    x[:, 9] = cost / cost.max() if cost.max() > 0 else 0.0
    x[:, 10] = (est - est.min()) / spread if spread > 0 else 0.0
    x[:, 11] = PRIORITY_WEIGHT.get(task.priority, 1.0) / 4.0
    x[:, 12] = np.log10(max(task.deadline_s, 1e-3)) / 2.0
    return [n.id for n in nodes], x


class DQNParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episodes: int = Field(30, ge=1, le=2000, description="Training episodes, each on a fresh workload.")
    episode_s: float = Field(
        600.0,
        title="Episode length",
        ge=60,
        le=86_400,
        description="Simulated time per training episode.",
        json_schema_extra={"x-unit": "s"},
    )
    hidden: int = Field(32, ge=4, le=256, description="Neurons in each of the two hidden layers.")
    gamma: float = Field(0.5, ge=0.0, le=0.99, description="Discount on the value of the next decision.")
    lr: float = Field(1e-3, title="Learning rate", gt=0, le=0.1, json_schema_extra={"x-advanced": True})
    batch: int = Field(64, ge=8, le=1024, json_schema_extra={"x-advanced": True})
    buffer: int = Field(30_000, ge=1000, le=500_000, json_schema_extra={"x-advanced": True})
    updates_per_episode: int = Field(300, ge=1, le=100_000, json_schema_extra={"x-advanced": True})
    target_sync: int = Field(
        100,
        ge=1,
        le=100_000,
        description="Gradient steps between target-network updates.",
        json_schema_extra={"x-advanced": True},
    )
    epsilon_start: float = Field(1.0, ge=0, le=1, json_schema_extra={"x-advanced": True})
    epsilon_end: float = Field(0.05, ge=0, le=1, json_schema_extra={"x-advanced": True})
    lambda_energy: float = Field(0.1, ge=0, description="Reward penalty for relative energy of the chosen node.")
    lambda_cost: float = Field(0.1, ge=0, description="Reward penalty for relative cloud cost of the chosen node.")
    train_seed: int = Field(
        1_000_003,
        ge=0,
        description="First training-workload seed (episodes use train_seed + episode).",
        json_schema_extra={"x-advanced": True},
    )


class _Learner(Placement):
    """Online placement driven by a DQN agent; records decisions when training."""

    def __init__(self, agent: DQNAgent, epsilon: float = 0.0, rng: np.random.Generator | None = None) -> None:
        self.agent, self.epsilon = agent, epsilon
        self.explore_rng = rng or np.random.default_rng(0)
        self.decisions: list[tuple[int, np.ndarray, int]] = []  # (task id, candidate features, chosen index)
        self.record = rng is not None

    def place(self, task: Task, view: ClusterView) -> str | None:
        ids, x = candidate_features(task, view)
        if not ids:
            return None
        k = min(len(ids), self.agent.cfg.max_actions)
        a = self.agent.act(x[:k], self.epsilon, self.explore_rng)
        if self.record:
            self.decisions.append((task.id, x[:k].astype(np.float32), a))
        return ids[a]


def _reward(rec, feats: np.ndarray, p: DQNParams) -> float:
    w = PRIORITY_WEIGHT.get(rec.task.priority, 1.0)
    base = w if rec.deadline_met else -w
    return base - p.lambda_energy * float(feats[8]) - p.lambda_cost * float(feats[9])


def train_dqn(
    topology: Topology,
    spec: WorkloadSpec,
    settings: SimSettings,
    p: DQNParams,
    progress: Callable[[float, str], None] | None = None,
) -> tuple[DQNAgent, list[dict[str, float]]]:
    reg = get_registry()
    cfg = DQNConfig(
        n_features=len(FEATURES),
        hidden=p.hidden,
        gamma=p.gamma,
        lr=p.lr,
        batch=p.batch,
        buffer=p.buffer,
        max_actions=max(1, len([n for n in topology.nodes if n.can_compute])),
        target_sync=p.target_sync,
    )
    agent = DQNAgent(cfg, np.random.default_rng([p.train_seed, 1]))
    update_rng = np.random.default_rng([p.train_seed, 2])
    ep_spec = spec.model_copy(update={"duration_s": p.episode_s})
    history: list[dict[str, float]] = []
    for e in range(p.episodes):
        frac = e / max(p.episodes - 1, 1)
        eps = p.epsilon_start + (p.epsilon_end - p.epsilon_start) * frac
        trace = generate_trace(ep_spec, topology, p.train_seed + e)
        learner = _Learner(agent, eps, np.random.default_rng([p.train_seed, 3, e]))
        sim = simulate(topology, trace, learner, reg.create("queue_discipline:fcfs"), settings, seed=p.train_seed + e)
        decisions = sorted(learner.decisions, key=lambda d: sim.records[d[0]].task.arrival_s)
        rewards = []
        for i, (tid, x, a) in enumerate(decisions):
            r = _reward(sim.records[tid], x[a], p)
            rewards.append(r)
            nxt = decisions[i + 1][1] if i + 1 < len(decisions) else None
            agent.buffer.add(x[a], r, nxt)
        losses = [agent.update(update_rng) for _ in range(p.updates_per_episode)]
        losses = [x for x in losses if np.isfinite(x)]
        m = compute_metrics(sim)
        history.append(
            {
                "episode": e + 1,
                "epsilon": eps,
                "mean_reward": float(np.mean(rewards)) if rewards else float("nan"),
                "deadline_success_rate": m["deadline_success_rate"],
                "energy_dynamic_j": m["energy_dynamic_j"],
                "loss": float(np.mean(losses)) if losses else float("nan"),
            }
        )
        if progress:
            progress((e + 1) / p.episodes, f"Training episode {e + 1} of {p.episodes}")
    return agent, history


_CACHE: dict[str, tuple[dict[str, list], list[dict[str, float]]]] = {}


def _cache_key(topology: Topology, spec: WorkloadSpec, settings: SimSettings, p: DQNParams) -> str:
    payload = json.dumps(
        [topology.sha256, spec.model_dump(mode="json"), settings.model_dump(mode="json"), p.model_dump(mode="json")],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def trained_policy(
    topology: Topology,
    spec: WorkloadSpec,
    settings: SimSettings,
    p: DQNParams,
    progress: Callable[[float, str], None] | None = None,
) -> tuple[DQNAgent, list[dict[str, float]]]:
    """Train (or reuse a cached) agent for this network, workload generator and settings."""
    key = _cache_key(topology, spec, settings, p)
    if key not in _CACHE:
        agent, history = train_dqn(topology, spec, settings, p, progress)
        _CACHE[key] = (agent.state_dict(), history)
    state, history = _CACHE[key]
    cfg = DQNConfig(
        n_features=len(FEATURES),
        hidden=p.hidden,
        max_actions=max(1, len([n for n in topology.nodes if n.can_compute])),
    )
    agent = DQNAgent(cfg, np.random.default_rng(0))
    agent.load(state)
    return agent, history


@register(
    kind=PluginKind.PLACEMENT,
    key="dqn",
    name="Deep Q-Network (learned)",
    version="1.0.0",
    status=IMPL,
    summary="Online scheduler learned by a small DQN, trained on fresh simulated workloads before it is used.",
    description=(
        "Scores each eligible node with a Q-network over scale-free features and picks the best. Training uses "
        "experience replay, a target network and Double-DQN targets, on workloads with seeds disjoint from "
        "evaluation seeds. Needs a generated workload (it trains on new samples from the same generator)."
    ),
    references=[
        "Mnih et al., Human-level control through deep reinforcement learning, Nature 518, 2015",
        "van Hasselt, Guez and Silver, Deep reinforcement learning with double Q-learning, AAAI 2016",
    ],
    params=DQNParams,
    layers=ALL_LAYERS,
    tags=["baseline", "learned", "reinforcement-learning"],
    phase=4,
)
class DQNPlacement(Placement):
    def __init__(self, params: DQNParams | None = None) -> None:
        self.p = params or DQNParams()
        self.agent: DQNAgent | None = None

    def reset(self, view: ClusterView, rng: np.random.Generator) -> None:
        super().reset(view, rng)
        topology, spec, settings = view.training_context()
        if spec is None:
            raise ValueError(
                "The DQN placement trains on fresh workloads from the workload generator, so it cannot run on a "
                "fixed trace (for example retrieval or dataset tasks)."
            )
        self.agent, _ = trained_policy(topology, spec, settings, self.p)
        self._inner = _Learner(self.agent)

    def place(self, task: Task, view: ClusterView) -> str | None:
        return self._inner.place(task, view)


@register(
    kind=PluginKind.OPTIMIZER,
    key="dqn",
    name="Deep Q-Network",
    version="1.0.0",
    status=IMPL,
    summary="Two-layer Q-network in numpy with replay, target network and Double-DQN targets. No GPU needed.",
    description="The learner behind placement:dqn and the DQN training experiment.",
    references=["Mnih et al., Human-level control through deep reinforcement learning, Nature 518, 2015"],
    params=DQNParams,
    layers=["edge", "fog", "cloud"],
    tags=["learned", "reinforcement-learning"],
    phase=4,
)
class DQNOptimizer:
    def __init__(self, params: DQNParams | None = None) -> None:
        self.p = params or DQNParams()

    def train(self, topology: Topology, spec: WorkloadSpec, settings: SimSettings):
        return train_dqn(topology, spec, settings, self.p)


DQN_BASELINES = ["mct", "edge_ward", "least_loaded", "random"]
POLICY_NAMES = {
    "dqn": "DQN (learned)",
    "mct": "MCT",
    "edge_ward": "Edge-ward",
    "least_loaded": "Least loaded",
    "random": "Random",
}
DQN_METRICS = [
    "deadline_success_rate",
    "urgent_deadline_success_rate",
    "mean_response_s",
    "p95_response_s",
    "energy_dynamic_j",
    "cost",
    "scheduling_overhead_us",
]


class DQNTrainingParams(ScenarioParams, DQNParams):
    evaluation_replications: int = Field(
        10, ge=2, le=100, description="Held-out workloads the trained policy and the baselines are compared on."
    )
    base_seed: int = Field(1, title="Evaluation seed", ge=0, description="Evaluation workloads use base_seed + r.")


@register(
    kind=PluginKind.SIMULATION,
    key="dqn_training",
    name="DQN training and evaluation",
    version="1.0.0",
    status=IMPL,
    summary="Trains the DQN scheduler on fresh workloads, then compares it with online baselines on held-out ones.",
    description=(
        "Shows the learning curve (reward, deadlines met, energy, loss per episode) and a replicated comparison "
        "with MCT, edge-ward, least-loaded and random placement on identical held-out workloads."
    ),
    params=DQNTrainingParams,
    layers=["edge", "fog", "cloud"],
    outputs=["Learning curve", "Comparison with baselines", "Statistics"],
    phase=4,
    tags=["simulation", "learned", "experiment"],
)
class DQNTraining:
    def __init__(self, params: DQNTrainingParams) -> None:
        self.p = params

    def run(self, progress: ProgressReporter = null_progress) -> dict[str, Any]:
        p = self.p
        topo, spec, settings = p.build()
        dqn_p = DQNParams(**{k: getattr(p, k) for k in DQNParams.model_fields})
        t0 = time.perf_counter()
        _, history = trained_policy(topo, spec, settings, dqn_p, lambda f, m: progress(0.02 + 0.6 * f, m))
        train_s = time.perf_counter() - t0
        reg = get_registry()
        policies = ["dqn"] + DQN_BASELINES
        per: dict[str, list[dict[str, float]]] = {k: [] for k in policies}
        total = p.evaluation_replications * len(policies)
        done = 0
        for r in range(p.evaluation_replications):
            seed = p.base_seed + r
            trace = generate_trace(spec, topo, seed)
            for k in policies:
                placement = (
                    reg.create("placement:dqn", dqn_p.model_dump()) if k == "dqn" else reg.create(f"placement:{k}")
                )
                sim = simulate(topo, trace, placement, reg.create("queue_discipline:fcfs"), settings, seed=seed)
                per[k].append(compute_metrics(sim))
                done += 1
                progress(0.62 + 0.36 * done / total, f"Evaluation run {done} of {total}")
        table = {k: {m: summarize([x[m] for x in per[k]]) for m in DQN_METRICS} for k in policies}
        # Statistics are keyed by display name, so verdicts read "MCT is better", not "mct".
        stats = {
            m: compare({POLICY_NAMES[k]: [x[m] for x in per[k]] for k in policies}, higher_is_better=hib)
            for m, hib in (("deadline_success_rate", True), ("energy_dynamic_j", False), ("mean_response_s", False))
        }
        out = {
            "data_origin": str(DataOrigin.SYNTHETIC),
            "kind": "simulation.dqn_training",
            "params": p.model_dump(mode="json"),
            "features": FEATURES,
            "history": history,
            "training_seconds": round(train_s, 2),
            "policies": policies,
            "names": {k: POLICY_NAMES[k] for k in policies},
            "metrics": DQN_METRICS,
            "table": table,
            "stats": stats,
            "provenance": {"topology_sha256": topo.sha256, **_environment()},
            "summary": {
                "episodes": p.episodes,
                "evaluation_replications": p.evaluation_replications,
                "final_training_deadline_rate": history[-1]["deadline_success_rate"],
                "dqn_deadline_rate": table["dqn"]["deadline_success_rate"]["mean"],
                "verdict": stats["deadline_success_rate"]["verdict"],
            },
        }
        return _clean(out)
