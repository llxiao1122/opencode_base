import logging

logger = logging.getLogger(__name__)


def handle(content: str, context: str = ""):
    """纠错写入独立纠错库（系统自身成长），与人员/流程档案解耦。

    不写人员档案（update_entity）、不进 ringbuf/pending（record），
    避免纠错内容污染实体档案或触发批量合入。
    会话应答前由 engine.run() 全文加载纠错库。
    """
    text = (context + "：" + content) if context and not content.startswith(context) else content
    try:
        from skills.memory.correction_store import append
        added = append(text)
    except Exception as e:
        logger.warning("correction store append failed: %s", e, exc_info=True)
        added = False
    if not added:
        return "[Cipher:correction]\n✅ 已记录（重复，未新增）"
    return "[Cipher:correction]\n✅ 纠正已记录（系统成长库）"
