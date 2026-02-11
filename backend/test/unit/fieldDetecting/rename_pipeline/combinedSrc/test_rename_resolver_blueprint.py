"""Blueprint for unit tests of `rename_resolver.py`.

Required coverage:
- normalization helpers:
  - `_to_snake_case`, `_normalize_name`, checkbox helpers
- confidence/category helpers
- deterministic tag generation helpers
- OpenAI line/rule parsing helpers
- `_dedupe_field_names`
- `run_openai_rename_pipeline` orchestration with mocked boundaries

Edge cases:
- malformed OpenAI output lines
- duplicate/invalid candidate names
- mixed checkbox grouping metadata

Important context:
- This file contains the core rename decision logic and rule extraction.
"""
