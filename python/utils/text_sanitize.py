"""
Shared input sanitizer. Strips HTML tags (defeats stored XSS) and collapses
CR/LF/tab characters (defeats email-header and log-line injection) from any
free-text field before it touches a database, an email, or a log line.
"""

import re

import bleach


def clean_text(value: str) -> str:
    value = bleach.clean(value, tags=[], attributes={}, strip=True)
    value = re.sub(r"[\r\n\t]+", " ", value)
    return value.strip()
