"""
task/status.py — Task status constants.
"""

PENDING = "pending"
IN_PROGRESS = "in_progress"
COMPLETED = "completed"

EXECUTOR_PENDING = "pending"
EXECUTOR_DONE = "done"

ALL_TASK_STATUSES = [PENDING, IN_PROGRESS, COMPLETED]
ALL_EXECUTOR_STATUSES = [EXECUTOR_PENDING, EXECUTOR_DONE]
