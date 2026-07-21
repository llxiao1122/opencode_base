"""
task/status.py — Task status constants.
"""

PENDING = "pending"
IN_PROGRESS = "in_progress"
COMPLETED = "completed"
PENDING_CONFIRM = "pending_confirm"

EXECUTOR_PENDING = "pending"
EXECUTOR_DONE = "done"

ALL_TASK_STATUSES = [PENDING, IN_PROGRESS, COMPLETED, PENDING_CONFIRM]
ALL_EXECUTOR_STATUSES = [EXECUTOR_PENDING, EXECUTOR_DONE]
