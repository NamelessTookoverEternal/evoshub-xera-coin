"""
Email sender — plug in SMTP credentials via .env
"""

import os
import smtplib
from email.mime.text import MIMEText


def send_email(to: str, subject: str, body: str) -> bool:
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"]    = os.getenv("EMAIL_USER")
        msg["To"]      = to

        with smtplib.SMTP(os.getenv("EMAIL_HOST", "smtp.gmail.com"),
                          int(os.getenv("EMAIL_PORT", 587))) as server:
            server.starttls()
            server.login(os.getenv("EMAIL_USER"), os.getenv("EMAIL_PASS"))
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False
