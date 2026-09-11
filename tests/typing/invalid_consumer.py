"""These calls must be rejected by an installed-package type checker."""

from ton import api

api.EngineOptions(seed="bad")
api.generate({}, proof_sample_rate="bad")
api.ChildCall("bad", None)
api.EngineOptions(validators={"bad": object()})
api.fork_engine({}, parent_seed=1, worker_id=0, options={"seed": 1})
