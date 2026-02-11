"""Blueprint for unit tests of `backend/detection_status.py` constants.

Required coverage:
- exported constants exist and are stable:
  - queued, running, complete, failed
- values are unique and non-empty strings

Important context:
- These status literals are shared by API responses, detector service, and Firestore logs.
"""
