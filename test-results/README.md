# test-results/

Output from test runs (temporary artifacts).

## Cleanup

```bash
python3 test-results/cleanOutput.py --all
```

Use `--last-run` to remove only `.last-run.json`, or `--dry-run` to preview.

## `.last-run.json`

`.last-run.json` is optional runner metadata used by "last run/last failed" retry flows.
Removing it only resets that pointer state; it does not affect source tests.
