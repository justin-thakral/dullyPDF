"""Blueprint for unit tests of `backend/detection_tasks.py`.

Required coverage:
- `resolve_detector_profile(page_count)`:
  - heavy selected only when heavy config exists and threshold met
  - otherwise light
- `resolve_task_config(profile)`:
  - profile-specific env overrides base values
  - trailing slash stripped from service URL
  - missing env set raises clear RuntimeError
- `enqueue_detection_task(payload, profile)`:
  - builds `/internal/detect` URL
  - includes OIDC service account + audience
  - optional dispatch deadline handling
  - force-immediate schedule handling

Edge cases:
- invalid deadline env value
- Cloud Tasks import not available

Important context:
- This is the only queueing path for production detector orchestration.
"""
