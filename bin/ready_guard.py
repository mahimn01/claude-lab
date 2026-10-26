#!/usr/bin/env python3
"""Prevent a lab prompt from running if its routing plugin did not activate.

This hook reads only the lab readiness marker. It never launches Claude, changes
settings, reads credentials, or approves tools.
"""
import json
import os
from pathlib import Path

try:
    state = json.loads((Path(os.environ['CLAUDE_LAB_RUN_DIR'])/'metrics.json').read_text())
    ready = state.get('runtimeReady') is True
except (KeyError,OSError,ValueError):
    ready = False
print(json.dumps({} if ready else {'decision':'block','reason':'The lab routing plugin did not activate. Run claude-lab doctor. Your ordinary claude command is unchanged.'}))
