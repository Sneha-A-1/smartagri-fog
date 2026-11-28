"""DQN scheduler: gradients, learning on a toy problem, reproducibility and simulator use."""

from __future__ import annotations

import numpy as np
import pytest
import smartagri_core.plugins  # noqa: F401
from smartagri_core.registry import get_registry
from smartagri_core.sched.dqn import MLP, DQNAgent, DQNConfig
from smartagri_core.sim import dqn_placement
from smartagri_core.sim.dqn_placement import DQNParams, DQNTraining, DQNTrainingParams, train_dqn
from smartagri_core.sim.engine import simulate
from smartagri_core.sim.metrics import compute_metrics
from smartagri_core.sim.runner import ScenarioParams
from smartagri_core.sim.workload import Trace, generate_trace

FAST = {"episodes": 2, "episode_s": 120, "updates_per_episode": 20, "buffer": 2000}


def test_mlp_gradients_match_finite_differences():
    rng = np.random.default_rng(0)
    net = MLP([5, 7, 6, 1], rng)
    x = rng.normal(size=(4, 5))
    g_out = rng.normal(size=4)
    _, acts = net.forward(x, keep=True)
    grads = net.backward(acts, g_out)
    for p, g in zip(net.params(), grads, strict=True):
        idx = tuple(rng.integers(s) for s in p.shape)
        old = p[idx]
        p[idx] = old + 1e-6
        up = float(g_out @ net.forward(x))
        p[idx] = old - 1e-6
        down = float(g_out @ net.forward(x))
        p[idx] = old
        assert g[idx] == pytest.approx((up - down) / 2e-6, rel=1e-4, abs=1e-6)


def test_agent_learns_which_action_pays():
    """Two actions; the one whose first feature is 1 pays 1, the other pays 0. One-step episodes."""
    cfg = DQNConfig(n_features=3, hidden=16, gamma=0.0, lr=5e-3, batch=32, buffer=2000, max_actions=2)
    agent = DQNAgent(cfg, np.random.default_rng(1))
    rng = np.random.default_rng(2)
    for _ in range(1500):
        good = int(rng.integers(2))
        feats = np.zeros((2, 3))
        feats[good, 0] = 1.0
        feats[:, 1:] = rng.normal(size=(2, 2))
        a = agent.act(feats, 0.5, rng)
        agent.buffer.add(feats[a], float(a == good), None)
        agent.update(rng)
    hits = 0
    for _ in range(200):
        good = int(rng.integers(2))
        feats = np.zeros((2, 3))
        feats[good, 0] = 1.0
        feats[:, 1:] = rng.normal(size=(2, 2))
        hits += agent.act(feats, 0.0, rng) == good
    assert hits >= 190


def _scenario():
    return ScenarioParams(duration_s=120).build()


def test_training_is_reproducible():
    topo, spec, settings = _scenario()
    a, ha = train_dqn(topo, spec, settings, DQNParams(**FAST))
    b, hb = train_dqn(topo, spec, settings, DQNParams(**FAST))
    assert ha == hb
    for wa, wb in zip(a.online.params(), b.online.params(), strict=True):
        assert np.array_equal(wa, wb)


def test_dqn_placement_runs_reproducibly_and_is_cached():
    topo, spec, settings = _scenario()
    trace = generate_trace(spec, topo, 5)
    reg = get_registry()
    dqn_placement._CACHE.clear()

    def run():
        sim = simulate(
            topo, trace, reg.create("placement:dqn", FAST), reg.create("queue_discipline:fcfs"), settings, seed=5
        )
        return compute_metrics(sim), [r.node for r in sim.records.values()]

    m1, n1 = run()
    m2, n2 = run()
    assert len(dqn_placement._CACHE) == 1, "the second run must reuse the trained policy"
    assert n1 == n2 and m1["completion_rate"] == 100.0


def test_dqn_refuses_a_fixed_trace():
    topo, spec, settings = _scenario()
    trace = generate_trace(spec, topo, 5)
    fixed = Trace(spec_name="fixed", seed=0, tasks=trace.tasks)
    assert fixed == Trace(spec_name="fixed", seed=0, tasks=trace.tasks, spec=spec), "spec must not affect equality"
    reg = get_registry()
    with pytest.raises(ValueError, match="fresh workloads"):
        simulate(topo, fixed, reg.create("placement:dqn", FAST), reg.create("queue_discipline:fcfs"), settings, seed=1)


def test_training_plugin_reports_curve_and_comparison():
    params = DQNTrainingParams(duration_s=120, evaluation_replications=2, **FAST)
    out = DQNTraining(params).run()
    assert out["kind"] == "simulation.dqn_training"
    assert len(out["history"]) == 2
    assert set(out["table"]) == {"dqn", "mct", "edge_ward", "least_loaded", "random"}
    assert out["stats"]["deadline_success_rate"]["verdict"]
    reg = get_registry()
    assert reg.get("placement:dqn").runnable and not reg.get("placement:dqn").startable
    assert reg.get("simulation:dqn_training").startable
    assert not reg.get("optimizer:ppo").runnable
