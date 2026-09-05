MAX_RESULT_CHARS = 4000


def truncate(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    """Cut the middle out, not the tail. The end of a traceback is the useful half."""
    if len(text) <= limit:
        return text
    head, tail = text[: limit // 2], text[-limit // 2 :]
    return f"{head}\n\n... [{len(text) - limit} characters omitted] ...\n\n{tail}"
