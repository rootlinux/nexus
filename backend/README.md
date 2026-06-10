# Backend Test Environment

The canonical supported backend test environment is `backend/.venv`.

Use:

```bash
backend/scripts/bootstrap_test_env.sh
backend/scripts/run_targeted_security_tests.sh all
```

Notes:

- Do not use root `.venv311` or `backend/venv`; those paths are deprecated and should not be recreated.
- If a backend test or script needs Python or Alembic directly, it should resolve them from `backend/.venv/bin/`.
