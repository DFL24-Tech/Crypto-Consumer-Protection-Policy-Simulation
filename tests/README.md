# DFL24-Sim test suite

Fast, deterministic tests that guard the platform's invariants. Each file targets one
subsystem so contributors know exactly where a new test belongs.

| File | Covers |
|------|--------|
| `test_behavior.py` | Dual-process decisions; point-of-action friction precision |
| `test_market.py`   | Endogenous bubbles/crashes; size-invariant depth scaling |
| `test_policy.py`   | The coverage gap; detection collapse under adaptive adversaries |
| `test_network.py`  | Scale-free graph: hubs present, no isolates |
| `test_scenarios.py`| The 12 scenarios; liquidation, alert fatigue, grooming; the battery |
| `conftest.py`      | Shared fixtures (`small_cfg`) and helpers (`run_small`, `detection`) |

## Running

```bash
pip install -e ".[dev]"     # or: pip install pytest
pytest -q                    # whole suite (seconds)
pytest tests/test_policy.py  # one module
pytest -k coverage_gap       # one test by name
```

## Adding a test

1. Put it in the file for the subsystem it exercises (create `test_<subsystem>.py` if new).
2. Use the helpers in `conftest.py` rather than re-instantiating configs:
   ```python
   from conftest import run_small, detection
   def test_my_invariant():
       s = run_small(n_agents=4000, steps=14, seed=0)
       assert s["friction_precision"] == 1.0
   ```
3. Keep tests small and seeded (N ≤ 5,000, fixed `seed=`) so the suite stays fast and
   reproducible. Assert on **invariants and orderings** (e.g. "adaptation lowers
   detection"), not on exact floating-point values, which depend on the seed.
4. If you add a scenario or an engine mechanism, add a test that proves the mechanism
   actually fires (see `test_liquidation_cascade_fires` for the pattern).
