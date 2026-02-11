"""Blueprint for unit tests of `backend/ai/rename_pipeline.py`.

Required coverage:
- `_build_candidates` page metadata + label collation
- debug artifact writing path (`_write_json`) when debug enabled
- `run_openai_rename_on_pdf` orchestration order and argument plumbing

Edge cases:
- empty labels for page
- pages with missing metadata defaults

Important context:
- This is the orchestrator between rendering/label extraction and OpenAI rename resolver.
"""
