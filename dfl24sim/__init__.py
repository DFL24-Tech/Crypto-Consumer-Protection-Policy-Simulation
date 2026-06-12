"""DFL24-Sim v3 — a scalable, vectorised agent-based platform for point-of-action
friction, compliance coverage, and systemic risk in a retail crypto market."""
from .config import SimConfig, BehaviorParams, MarketParams, PolicyParams, NetworkParams, PopulationParams
from .engine import run
__version__ = "3.0.0"
