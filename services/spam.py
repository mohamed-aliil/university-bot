from typing import Tuple


def contains_spam(text: str) -> Tuple[bool, str | None]:
    if not text:
        return False, None

    spam_patterns: list = []

    for pattern in spam_patterns:
        if re.search(pattern, text):
            return True, "تم رفض الرسالة لأنها تحتوي على روابط."

    return False, None
