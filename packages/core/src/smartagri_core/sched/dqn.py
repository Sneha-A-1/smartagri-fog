"""A small Deep Q-Network in pure numpy, sized for a laptop.

The network scores one (state, action) pair at a time: its input is a feature vector describing a task and one
candidate node in the current system state, and its output is that action's Q-value. Because the number of
eligible nodes changes from decision to decision, scoring each candidate separately avoids a fixed action
space. Learning uses experience replay, a target network that is synchronised periodically, Double-DQN targets
(the online network picks the next action, the target network values it) and the Huber loss, optimised with
Adam (Mnih et al., 2015; van Hasselt, Guez and Silver, 2016; Kingma and Ba, 2015).

Every source of randomness is a ``numpy.random.Generator`` passed in, so training is reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


class MLP:
    """Fully connected network with ReLU hidden layers and one linear output."""

    def __init__(self, sizes: list[int], rng: np.random.Generator) -> None:
        self.W = [rng.normal(0.0, np.sqrt(2.0 / a), (a, b)) for a, b in zip(sizes[:-1], sizes[1:], strict=True)]
        self.b = [np.zeros(b) for b in sizes[1:]]

    def params(self) -> list[np.ndarray]:
        return self.W + self.b

    def copy_from(self, other: MLP) -> None:
        self.W = [w.copy() for w in other.W]
        self.b = [b.copy() for b in other.b]

    def forward(self, x: np.ndarray, keep: bool = False):
        acts = [x]
        h = x
        for i, (w, b) in enumerate(zip(self.W, self.b, strict=True)):
            h = h @ w + b
            if i < len(self.W) - 1:
                h = np.maximum(h, 0.0)
            acts.append(h)
        out = h[..., 0]
        return (out, acts) if keep else out

    def backward(self, acts: list[np.ndarray], grad_out: np.ndarray) -> list[np.ndarray]:
        """Gradients of sum(grad_out * output) with respect to W then b."""
        g = grad_out[:, None]
        gw: list[np.ndarray] = [np.empty(0)] * len(self.W)
        gb: list[np.ndarray] = [np.empty(0)] * len(self.W)
        for i in range(len(self.W) - 1, -1, -1):
            gw[i] = acts[i].T @ g
            gb[i] = g.sum(axis=0)
            if i:
                g = (g @ self.W[i].T) * (acts[i] > 0)
        return gw + gb


class Adam:
    def __init__(self, params: list[np.ndarray], lr: float, b1: float = 0.9, b2: float = 0.999) -> None:
        self.lr, self.b1, self.b2, self.t = lr, b1, b2, 0
        self.m = [np.zeros_like(p) for p in params]
        self.v = [np.zeros_like(p) for p in params]

    def step(self, params: list[np.ndarray], grads: list[np.ndarray]) -> None:
        self.t += 1
        for p, g, m, v in zip(params, grads, self.m, self.v, strict=True):
            m *= self.b1
            m += (1 - self.b1) * g
            v *= self.b2
            v += (1 - self.b2) * g * g
            mh = m / (1 - self.b1**self.t)
            vh = v / (1 - self.b2**self.t)
            p -= self.lr * mh / (np.sqrt(vh) + 1e-8)


@dataclass(frozen=True)
class DQNConfig:
    n_features: int
    hidden: int = 32
    gamma: float = 0.5
    lr: float = 1e-3
    batch: int = 64
    buffer: int = 30_000
    max_actions: int = 16
    target_sync: int = 100
    huber: float = 1.0


class ReplayBuffer:
    """Transitions (features of the chosen action, reward, candidate features of the next state, done)."""

    def __init__(self, cfg: DQNConfig) -> None:
        self.cap, self.k, self.n, self.i = cfg.buffer, cfg.max_actions, 0, 0
        self.x = np.zeros((self.cap, cfg.n_features), np.float32)
        self.r = np.zeros(self.cap, np.float32)
        self.nx = np.zeros((self.cap, self.k, cfg.n_features), np.float32)
        self.nmask = np.zeros((self.cap, self.k), bool)
        self.done = np.zeros(self.cap, bool)

    def add(self, x: np.ndarray, r: float, next_feats: np.ndarray | None) -> None:
        j = self.i
        self.x[j], self.r[j] = x, r
        self.nmask[j] = False
        if next_feats is None or len(next_feats) == 0:
            self.done[j] = True
        else:
            k = min(len(next_feats), self.k)
            self.nx[j, :k] = next_feats[:k]
            self.nmask[j, :k] = True
            self.done[j] = False
        self.i = (self.i + 1) % self.cap
        self.n = min(self.n + 1, self.cap)

    def sample(self, rng: np.random.Generator, size: int):
        idx = rng.integers(self.n, size=size)
        return self.x[idx], self.r[idx], self.nx[idx], self.nmask[idx], self.done[idx]


class DQNAgent:
    def __init__(self, cfg: DQNConfig, rng: np.random.Generator) -> None:
        self.cfg = cfg
        sizes = [cfg.n_features, cfg.hidden, cfg.hidden, 1]
        self.online = MLP(sizes, rng)
        self.target = MLP(sizes, rng)
        self.target.copy_from(self.online)
        self.opt = Adam(self.online.params(), cfg.lr)
        self.buffer = ReplayBuffer(cfg)
        self.updates = 0

    def q(self, feats: np.ndarray) -> np.ndarray:
        return self.online.forward(np.asarray(feats, dtype=float))

    def act(self, feats: np.ndarray, epsilon: float, rng: np.random.Generator) -> int:
        if epsilon > 0 and rng.random() < epsilon:
            return int(rng.integers(len(feats)))
        return int(np.argmax(self.q(feats)))

    def update(self, rng: np.random.Generator) -> float:
        """One gradient step on a replay minibatch. Returns the mean Huber loss."""
        cfg = self.cfg
        if self.buffer.n < cfg.batch:
            return float("nan")
        x, r, nx, mask, done = self.buffer.sample(rng, cfg.batch)
        b, k, f = nx.shape
        flat = nx.reshape(b * k, f).astype(float)
        q_on = self.online.forward(flat).reshape(b, k)
        q_tg = self.target.forward(flat).reshape(b, k)
        q_on = np.where(mask, q_on, -np.inf)
        best = np.argmax(q_on, axis=1)
        nxt = q_tg[np.arange(b), best]
        target = r + np.where(done, 0.0, cfg.gamma * nxt)
        pred, acts = self.online.forward(x.astype(float), keep=True)
        err = pred - target
        h = cfg.huber
        loss = np.where(np.abs(err) <= h, 0.5 * err**2, h * (np.abs(err) - 0.5 * h))
        grad = np.clip(err, -h, h) / b
        grads = self.online.backward(acts, grad)
        self.opt.step(self.online.params(), grads)
        self.updates += 1
        if self.updates % cfg.target_sync == 0:
            self.target.copy_from(self.online)
        return float(loss.mean())

    def state_dict(self) -> dict[str, list]:
        return {"W": [w.tolist() for w in self.online.W], "b": [b.tolist() for b in self.online.b]}

    def load(self, state: dict[str, list]) -> None:
        self.online.W = [np.array(w) for w in state["W"]]
        self.online.b = [np.array(b) for b in state["b"]]
        self.target.copy_from(self.online)
