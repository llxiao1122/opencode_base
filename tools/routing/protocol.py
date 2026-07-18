"""
protocol.py — 能力编排内部通信协议
Version: 1

定义了 composer.py 与各 handler 之间的返回值规范。
每一个 capability 执行完成后，返回统一的 CapabilityResult。
"""


class CapabilityResult:
    __slots__ = ("capability", "status", "result", "context",
                 "user_visible", "continue_exec", "error")

    def __init__(self, capability, status="success", result=None,
                 context="", user_visible=True, continue_exec=True, error=None):
        self.capability = capability
        self.status = status          # success | error
        self.result = result           # handler 原始返回值
        self.context = context         # ≤500字，传递给后续步骤
        self.user_visible = user_visible  # _compose 是否纳入用户回复
        self.continue_exec = continue_exec  # False → 终止后续步骤
        self.error = error             # 错误时存放异常信息

    def to_dict(self):
        return {slot: getattr(self, slot) for slot in self.__slots__}


def error_result(capability, error_msg):
    """能力执行失败时的工厂方法"""
    return CapabilityResult(
        capability=capability, status="error",
        error=error_msg, continue_exec=False, user_visible=False
    )
