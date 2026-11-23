"""Backward-compatibility module for cpp_review_service.

This module aliases cpp_review_service so that any import, call, or monkeypatch
of ``app.services.qwen_service`` transparently operates on ``cpp_review_service``.
"""

from __future__ import annotations

import sys

from app.services import cpp_review_service

# Re-export all public and internal attributes for static analyzers and IDEs
for _attr in dir(cpp_review_service):
    if not (_attr.startswith("__") and _attr.endswith("__")):
        globals()[_attr] = getattr(cpp_review_service, _attr)

# Alias in sys.modules so that runtime monkeypatching of either module affects both
sys.modules[__name__] = cpp_review_service
