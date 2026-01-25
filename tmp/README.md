# tmp/

Scratch files generated during local runs (PDF copies, CSVs, snapshots).

## Cleanup

```bash
python3 tmp/cleanOutput.py --all
```

Or target specific artifacts:

```bash
python3 tmp/cleanOutput.py --csvs --pdfs
python3 tmp/cleanOutput.py --snapshots
```

Use `--dry-run` to preview.
