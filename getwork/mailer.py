"""SMTP 邮件发送（SMTP_SSL，QQ/网易授权码）。"""

from __future__ import annotations

import logging
import os
import smtplib
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

log = logging.getLogger("getwork.mailer")


class MailerConfigError(Exception):
    """SMTP 未配置完整。"""


class MailAuthError(Exception):
    """授权码/账号认证失败。"""


class MailSendError(Exception):
    """SMTP 传输失败。"""


def _env(name: str) -> str:
    return os.getenv(name, "")


class Mailer:
    def __init__(self) -> None:
        self.host = _env("SMTP_HOST")
        self.port = int(_env("SMTP_PORT") or 465)
        self.user = _env("SMTP_USER")
        self.authcode = _env("SMTP_AUTHCODE")
        self.from_addr = _env("SMTP_FROM") or self.user
        self.default_to = _env("SMTP_TO")

    def configured(self) -> bool:
        return bool(self.host and self.user and self.authcode)


def send_email(
    to: str,
    subject: str,
    html: str,
    attachment_path: str | Path | None = None,
    mailer: Mailer | None = None,
) -> None:
    """发送 HTML 正文 + 可选附件的邮件。出错抛 MailAuthError / MailSendError。"""
    m = mailer or Mailer()
    if not m.configured():
        raise MailerConfigError(
            "SMTP 未配置：请在 .env 中填写 SMTP_HOST/SMTP_USER/SMTP_AUTHCODE（QQ/网易需用授权码）"
        )

    msg = MIMEMultipart("related")
    msg["Subject"] = str(Header(subject, "utf-8"))
    msg["From"] = formataddr(("getWork 岗位简报", m.from_addr))
    msg["To"] = to
    msg.preamble = "This is a multi-part message in MIME format."

    msg_alt = MIMEMultipart("alternative")
    msg_alt.attach(MIMEText(html, "html", "utf-8"))
    msg.attach(msg_alt)

    if attachment_path:
        p = Path(attachment_path)
        if p.exists():
            part = MIMEApplication(p.read_bytes(), _subtype="png")
            part.add_header(
                "Content-Disposition",
                "attachment",
                filename=("utf-8", "", p.name),
            )
            msg.attach(part)
        else:
            log.warning("附件不存在，忽略: %s", p)

    try:
        with smtplib.SMTP_SSL(m.host, m.port, timeout=30) as server:
            server.login(m.user, m.authcode)
            server.sendmail(m.from_addr, [to], msg.as_string())
    except smtplib.SMTPAuthenticationError as e:
        raise MailAuthError(f"SMTP 认证失败（授权码可能错误）: {e}") from e
    except (smtplib.SMTPException, OSError) as e:
        raise MailSendError(f"SMTP 发送失败: {e}") from e
