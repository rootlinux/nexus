from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Iterable

from app.core.config import settings
from app.schemas.feedback import FeedbackAttachmentReference
EMAIL_BACKGROUND = "#f5f1ea"
EMAIL_SURFACE = "#ffffff"
EMAIL_TEXT = "#1f1a17"
EMAIL_MUTED = "#6f6258"
EMAIL_BORDER = "#e8dfd4"
EMAIL_BUTTON = "#2b211a"
EMAIL_BUTTON_TEXT = "#ffffff"

logger = logging.getLogger(__name__)


def email_logo_url() -> str:
    return f"{settings.WEB_BASE_URL.rstrip('/')}/brand/apple-touch-icon.png"


@dataclass(frozen=True)
class MailMessage:
    to_email: str
    subject: str
    text_body: str
    from_email: str
    from_name: str
    html_body: str | None = None


class MailSender:
    async def send(self, message: MailMessage) -> None:
        raise NotImplementedError


class CaptureMailSender(MailSender):
    def __init__(self, output_dir: str) -> None:
        self.output_dir = Path(output_dir)

    def _candidate_output_dirs(self) -> tuple[Path, ...]:
        primary_dir = self.output_dir
        runtime_tmpdir = os.getenv("TMPDIR") or tempfile.gettempdir()
        fallback_root = Path(runtime_tmpdir) / "nexus-mail-capture"
        fallback_dir = (
            fallback_root / primary_dir
            if not primary_dir.is_absolute()
            else fallback_root / primary_dir.name
        )
        if fallback_dir == primary_dir:
            return (primary_dir,)
        return (primary_dir, fallback_dir)

    async def send(self, message: MailMessage) -> None:
        payload = {
            "to_email": message.to_email,
            "from_email": message.from_email,
            "from_name": message.from_name,
            "subject": message.subject,
            "text_body": message.text_body,
            "html_body": message.html_body,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }
        filename = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}_{message.to_email.replace('@', '_at_')}.json"
        serialized_payload = json.dumps(payload, indent=2)
        last_error: OSError | None = None
        for index, output_dir in enumerate(self._candidate_output_dirs()):
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / filename).write_text(serialized_payload, encoding="utf-8")
                if index > 0:
                    logger.warning(
                        "Mail capture directory unavailable; wrote capture payload to runtime fallback",
                        extra={"configured_dir": str(self.output_dir), "fallback_dir": str(output_dir)},
                    )
                return
            except OSError as exc:
                last_error = exc

        if last_error is not None:
            raise last_error


def configure_resend_api_key() -> None:
    import resend
    resend.api_key = settings.RESEND_API_KEY


class ResendMailSender(MailSender):
    def __init__(self) -> None:
        self.api_key = settings.RESEND_API_KEY

    async def send(self, message: MailMessage) -> None:
        import resend
        resend.api_key = self.api_key
        params = {
            "from": f"{message.from_name} <{message.from_email}>",
            "to": [message.to_email],
            "subject": message.subject,
            "text": message.text_body,
        }
        if message.html_body:
            params["html"] = message.html_body
        resend.Emails.send(params)


def get_mail_sender() -> MailSender:
    provider = settings.MAIL_PROVIDER.strip().lower()
    if provider == "capture":
        return CaptureMailSender(settings.MAIL_CAPTURE_DIR)
    if provider == "resend":
        configure_resend_api_key()
        return ResendMailSender()
    raise RuntimeError(f"Unsupported MAIL_PROVIDER: {settings.MAIL_PROVIDER}")


def _build_transactional_bodies(
    *,
    preview: str,
    headline: str,
    intro: str,
    cta_label: str,
    action_url: str,
    fallback_label: str,
    closing: str,
) -> tuple[str, str]:
    safe_preview = escape(preview)
    safe_headline = escape(headline)
    safe_intro = escape(intro)
    safe_cta_label = escape(cta_label)
    safe_fallback_label = escape(fallback_label)
    safe_closing = escape(closing)
    safe_action_url = escape(action_url, quote=True)
    safe_action_url_text = escape(action_url)
    safe_logo_url = escape(email_logo_url(), quote=True)

    text_body = (
        f"{headline}\n\n"
        f"{intro}\n\n"
        f"{cta_label}: {action_url}\n\n"
        f"{fallback_label}: {action_url}\n\n"
        f"{closing}"
    )

    html_body = f"""\
<!doctype html>
<html lang="en">
  <head>
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{safe_headline}</title>
  </head>
  <body style="margin:0;padding:0;background:{EMAIL_BACKGROUND};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:{EMAIL_TEXT};">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;mso-hide:all;color:transparent;">
      {safe_preview}
      &#8203;&#160;&#8203;&#160;&#8203;&#160;&#8203;&#160;&#8203;&#160;
    </div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:collapse;background:{EMAIL_BACKGROUND};margin:0;padding:0;">
      <tr>
        <td align="center" valign="top" style="padding:24px 12px;">
          <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" align="center" style="width:100%;max-width:600px;border-collapse:separate;background:{EMAIL_SURFACE};border:1px solid {EMAIL_BORDER};border-radius:18px;margin:0 auto;">
            <tr>
              <td align="center" style="padding:28px 28px 16px 28px;text-align:center;">
                <img src="{safe_logo_url}" alt="Nexus" width="56" height="56" style="display:block;margin:0 auto 14px auto;border:0;outline:none;text-decoration:none;border-radius:14px;">
                <div style="font-size:13px;line-height:1.4;letter-spacing:0.08em;text-transform:uppercase;color:{EMAIL_MUTED};">Nexus</div>
              </td>
            </tr>
            <tr>
              <td align="center" style="padding:0 28px 32px 28px;text-align:center;">
                <h1 style="margin:0 0 12px 0;font-size:26px;line-height:1.2;font-weight:600;color:{EMAIL_TEXT};text-align:center;">{safe_headline}</h1>
                <p style="margin:0 0 24px 0;font-size:16px;line-height:1.65;color:{EMAIL_TEXT};text-align:center;">{safe_intro}</p>
                <table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" style="margin:0 auto 24px auto;border-collapse:separate;">
                  <tr>
                    <td align="center" bgcolor="{EMAIL_BUTTON}" style="border-radius:999px;">
                      <a href="{safe_action_url}" style="display:inline-block;padding:14px 22px;font-size:15px;line-height:1.2;font-weight:600;color:{EMAIL_BUTTON_TEXT};text-decoration:none;">{safe_cta_label}</a>
                    </td>
                  </tr>
                </table>
                <p style="margin:0 0 8px 0;font-size:14px;line-height:1.6;color:{EMAIL_MUTED};text-align:center;">{safe_fallback_label}</p>
                <p style="margin:0 0 24px 0;padding:14px 16px;border:1px solid {EMAIL_BORDER};border-radius:12px;background:#fbf8f4;font-size:14px;line-height:1.7;word-break:break-word;text-align:center;">
                  <a href="{safe_action_url}" style="color:{EMAIL_TEXT};text-decoration:underline;">{safe_action_url_text}</a>
                </p>
                <p style="margin:0;font-size:14px;line-height:1.6;color:{EMAIL_MUTED};text-align:center;">{safe_closing}</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
    return text_body, html_body


def build_email_verification_message(*, to_email: str, verification_url: str) -> MailMessage:
    text_body, html_body = _build_transactional_bodies(
        preview="Verify your email to activate your Nexus account.",
        headline="Verify your email",
        intro="Verify your email to activate your Nexus account.",
        cta_label="Verify email",
        action_url=verification_url,
        fallback_label="If the button does not open, use this link",
        closing="If you did not create this account, you can ignore this email.",
    )
    return MailMessage(
        to_email=to_email,
        from_email=settings.MAIL_FROM_EMAIL,
        from_name=settings.MAIL_FROM_NAME,
        subject="Verify your Nexus email",
        text_body=text_body,
        html_body=html_body,
    )


def build_password_reset_message(*, to_email: str, reset_url: str) -> MailMessage:
    text_body, html_body = _build_transactional_bodies(
        preview="Use this link to reset your Nexus password.",
        headline="Reset your password",
        intro="We received a request to reset your Nexus password.",
        cta_label="Reset password",
        action_url=reset_url,
        fallback_label="If the button does not open, use this link",
        closing="If you did not request a reset, you can ignore this email.",
    )
    return MailMessage(
        to_email=to_email,
        from_email=settings.MAIL_FROM_EMAIL,
        from_name=settings.MAIL_FROM_NAME,
        subject="Reset your Nexus password",
        text_body=text_body,
        html_body=html_body,
    )


def build_email_change_message(*, to_email: str, verification_url: str) -> MailMessage:
    text_body, html_body = _build_transactional_bodies(
        preview="Confirm the new email on your Nexus account.",
        headline="Confirm your new email",
        intro="We received a request to change the email on your Nexus account.",
        cta_label="Confirm email change",
        action_url=verification_url,
        fallback_label="If the button does not open, use this link",
        closing="If you did not request this change, you can ignore this email.",
    )
    return MailMessage(
        to_email=to_email,
        from_email=settings.MAIL_FROM_EMAIL,
        from_name=settings.MAIL_FROM_NAME,
        subject="Confirm your new Nexus email",
        text_body=text_body,
        html_body=html_body,
    )


def _format_metadata_lines(metadata_items: Iterable[tuple[str, str | None]]) -> tuple[str, str]:
    text_lines: list[str] = []
    html_rows: list[str] = []
    for label, value in metadata_items:
        rendered_value = value if value else "Unavailable"
        text_lines.append(f"{label}: {rendered_value}")
        html_rows.append(
            f"<tr>"
            f"<td style=\"padding:8px 0;vertical-align:top;color:{EMAIL_MUTED};font-size:13px;line-height:1.5;width:170px;\">{escape(label)}</td>"
            f"<td style=\"padding:8px 0;vertical-align:top;color:{EMAIL_TEXT};font-size:13px;line-height:1.6;word-break:break-word;\">{escape(rendered_value)}</td>"
            f"</tr>"
        )
    return "\n".join(text_lines), "".join(html_rows)


def build_feedback_report_message(
    *,
    title: str,
    description: str,
    username: str | None,
    account_email: str | None,
    contact_email: str | None,
    current_path: str | None,
    current_url: str | None,
    device_info: str | None,
    user_agent: str | None,
    standalone_mode: bool | None,
    occurred_at: str | None,
    submitted_at: str,
    user_id: int | None,
    app_version: str | None,
    attachment: FeedbackAttachmentReference | None = None,
) -> MailMessage:
    safe_title = title.strip()
    safe_description = description.strip()
    metadata_items = [
        ("Username", username),
        ("User ID", str(user_id) if user_id is not None else None),
        ("Account email", account_email),
        ("Contact email", contact_email),
        ("Current path", current_path),
        ("Current URL", current_url),
        ("Device / browser", device_info),
        ("User agent", user_agent),
        ("PWA standalone", "Yes" if standalone_mode is True else "No" if standalone_mode is False else None),
        ("Client timestamp", occurred_at),
        ("Received at", submitted_at),
        ("App version", app_version),
        ("Attachment", "Included" if attachment else "None"),
    ]
    if attachment:
        metadata_items.extend(
            [
                ("Attachment filename", attachment.filename),
                ("Attachment content type", attachment.content_type),
                ("Attachment size", _format_attachment_size(attachment.size_bytes)),
                ("Attachment URL", attachment.access_url),
            ]
        )

    text_metadata, html_metadata = _format_metadata_lines(metadata_items)

    text_body = (
        f"Nexus feedback report\n\n"
        f"Title\n"
        f"{safe_title}\n\n"
        f"Description\n"
        f"{safe_description}\n\n"
        f"Metadata\n"
        f"{text_metadata}"
    )

    html_body = f"""\
<!doctype html>
<html lang="en">
  <head>
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escape(safe_title)}</title>
  </head>
  <body style="margin:0;padding:0;background:{EMAIL_BACKGROUND};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:{EMAIL_TEXT};">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:collapse;background:{EMAIL_BACKGROUND};margin:0;padding:24px 12px;">
      <tr>
        <td align="center" valign="top">
          <table role="presentation" width="640" cellpadding="0" cellspacing="0" border="0" align="center" style="width:100%;max-width:640px;border-collapse:separate;background:{EMAIL_SURFACE};border:1px solid {EMAIL_BORDER};border-radius:18px;margin:0 auto;">
            <tr>
              <td style="padding:28px 28px 10px 28px;">
                <div style="font-size:13px;line-height:1.4;letter-spacing:0.08em;text-transform:uppercase;color:{EMAIL_MUTED};">Nexus</div>
                <h1 style="margin:10px 0 0 0;font-size:24px;line-height:1.25;font-weight:600;color:{EMAIL_TEXT};">{escape(safe_title)}</h1>
              </td>
            </tr>
            <tr>
              <td style="padding:0 28px 18px 28px;">
                <div style="padding:16px 18px;border:1px solid {EMAIL_BORDER};border-radius:14px;background:#fbf8f4;font-size:14px;line-height:1.7;white-space:pre-wrap;">{escape(safe_description)}</div>
              </td>
            </tr>
            <tr>
              <td style="padding:0 28px 28px 28px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:collapse;">
                  {html_metadata}
                </table>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

    return MailMessage(
        to_email=settings.FEEDBACK_REPORT_TO_EMAIL,
        from_email=settings.MAIL_FROM_EMAIL,
        from_name=settings.MAIL_FROM_NAME,
        subject=f"[Nexus] {safe_title}",
        text_body=text_body,
        html_body=html_body,
    )


def _format_attachment_size(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB ({size_bytes} bytes)"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB ({size_bytes} bytes)"
    return f"{size_bytes} bytes"
