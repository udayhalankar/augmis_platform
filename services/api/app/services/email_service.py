# services/api/app/services/email_service.py
from __future__ import annotations

from dataclasses import dataclass
import html
import smtplib
import ssl

from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from services.api.app.core.config import settings


class EmailDeliveryError(Exception):
    pass


@dataclass(frozen=True)
class MailConfiguration:
    enabled: bool
    host: str
    port: int
    username: str
    password: str
    from_email: str
    from_name: str
    use_starttls: bool
    use_ssl: bool
    timeout_seconds: int


def mail_configuration_from_env() -> MailConfiguration:
    return MailConfiguration(
        enabled=settings.mail_enabled,
        host=settings.mail_host,
        port=settings.mail_port,
        username=settings.mail_username,
        password=settings.mail_password,
        from_email=settings.mail_from_email,
        from_name=settings.mail_from_name,
        use_starttls=settings.mail_use_starttls,
        use_ssl=settings.mail_use_ssl,
        timeout_seconds=settings.mail_timeout_seconds,
    )


def _validate_mail_configuration(
    mail_configuration: MailConfiguration,
) -> None:
    if not mail_configuration.enabled:
        raise EmailDeliveryError("Email delivery is not enabled.")

    if not mail_configuration.host.strip():
        raise EmailDeliveryError(
            "SMTP host is required when email delivery is enabled."
        )

    if not mail_configuration.from_email.strip():
        raise EmailDeliveryError(
            "Sender email is required when email delivery is enabled."
        )

    if mail_configuration.use_ssl and mail_configuration.use_starttls:
        raise EmailDeliveryError(
            "SSL/TLS and STARTTLS cannot both be enabled."
        )

    has_username = bool(mail_configuration.username.strip())
    has_password = bool(mail_configuration.password)

    if has_username != has_password:
        raise EmailDeliveryError(
            "SMTP username and credential must either both be configured or both be empty."
        )


def _send_message(
    message: EmailMessage,
    *,
    mail_configuration: MailConfiguration,
) -> str:
    _validate_mail_configuration(mail_configuration)

    if not message.get("Message-ID"):
        sender_domain = (
            mail_configuration.from_email.rsplit(
                "@",
                1,
            )[-1]
            if "@"
            in mail_configuration.from_email
            else "augmis.com"
        )

        message["Message-ID"] = (
            make_msgid(
                domain=sender_domain
            )
        )

    message_id = str(
        message["Message-ID"]
    )

    context = ssl.create_default_context()

    try:
        if mail_configuration.use_ssl:
            with smtplib.SMTP_SSL(
                host=mail_configuration.host,
                port=mail_configuration.port,
                timeout=mail_configuration.timeout_seconds,
                context=context,
            ) as smtp:
                if mail_configuration.username.strip():
                    smtp.login(
                        mail_configuration.username,
                        mail_configuration.password,
                    )
                smtp.send_message(message)
            return message_id

        with smtplib.SMTP(
            host=mail_configuration.host,
            port=mail_configuration.port,
            timeout=mail_configuration.timeout_seconds,
        ) as smtp:
            smtp.ehlo()

            if mail_configuration.use_starttls:
                smtp.starttls(context=context)
                smtp.ehlo()

            if mail_configuration.username.strip():
                smtp.login(
                    mail_configuration.username,
                    mail_configuration.password,
                )

            smtp.send_message(message)

        return message_id

    except (smtplib.SMTPException, OSError, TimeoutError) as error:
        raise EmailDeliveryError("SMTP delivery failed.") from error


def send_tenant_invitation_email(
    *,
    recipient_email: str,
    tenant_name: str,
    tenant_slug: str,
    role_names: list[str],
    acceptance_url: str,
    expires_at: datetime,
    reissued: bool = False,
    mail_configuration: MailConfiguration | None = None,
) -> str:
    config = mail_configuration or mail_configuration_from_env()

    clean_recipient = str(recipient_email or "").strip()
    if not clean_recipient:
        raise EmailDeliveryError("Invitation recipient email is required.")

    clean_tenant_name = str(tenant_name or "").strip()
    clean_tenant_slug = str(tenant_slug or "").strip()
    clean_roles = [
        str(role).strip()
        for role in role_names
        if str(role).strip()
    ]
    role_text = ", ".join(clean_roles) or "Tenant User"

    subject_prefix = "Updated invitation" if reissued else "Invitation"

    message = EmailMessage()
    message["Subject"] = (
        f"{subject_prefix} to join {clean_tenant_name} on AUGMIS"
    )
    message["From"] = formataddr(
        (config.from_name, config.from_email)
    )
    message["To"] = clean_recipient

    plain_body = f"""You have been invited to join {clean_tenant_name} on AUGMIS.

Workspace:
{clean_tenant_slug}

Roles:
{role_text}

Accept invitation:
{acceptance_url}

This invitation expires at:
{expires_at.isoformat()}

If you were not expecting this invitation, you can ignore this email.
"""
    message.set_content(plain_body)

    safe_tenant_name = html.escape(clean_tenant_name)
    safe_tenant_slug = html.escape(clean_tenant_slug)
    safe_role_text = html.escape(role_text)
    safe_acceptance_url = html.escape(acceptance_url, quote=True)
    safe_expires_at = html.escape(expires_at.isoformat())

    html_body = f"""
<html>
  <body style="margin:0;padding:0;background:#f4f6f8;font-family:Segoe UI,Arial,Helvetica,sans-serif;color:#17212b;">
    <div style="max-width:640px;margin:32px auto;background:#ffffff;border:1px solid #d9e0e5;">
      <div style="padding:24px 28px;border-bottom:1px solid #d9e0e5;">
        <strong style="font-size:20px;">AUGMIS</strong>
        <div style="margin-top:2px;color:#66727d;font-size:12px;">PLATFORM CONTROL PLANE</div>
      </div>
      <div style="padding:30px 28px;">
        <div style="color:#66727d;font-size:12px;text-transform:uppercase;letter-spacing:.08em;">Tenant Invitation</div>
        <h2>Join {safe_tenant_name}</h2>
        <p>You have been invited to access <strong>{safe_tenant_name}</strong> on AUGMIS.</p>
        <table style="width:100%;border-collapse:collapse;margin:24px 0;">
          <tr><td style="padding:8px;color:#66727d;">Workspace</td><td style="padding:8px;font-weight:600;">{safe_tenant_slug}</td></tr>
          <tr><td style="padding:8px;color:#66727d;">Roles</td><td style="padding:8px;font-weight:600;">{safe_role_text}</td></tr>
          <tr><td style="padding:8px;color:#66727d;">Expires</td><td style="padding:8px;font-weight:600;">{safe_expires_at}</td></tr>
        </table>
        <p>
          <a href="{safe_acceptance_url}" style="display:inline-block;padding:11px 18px;background:#1f5f8b;color:#ffffff;text-decoration:none;font-weight:600;border-radius:4px;">
            Accept Invitation
          </a>
        </p>
        <p style="margin-top:28px;color:#66727d;font-size:12px;">
          If you were not expecting this invitation, you can ignore this email.
        </p>
      </div>
    </div>
  </body>
</html>
"""
    message.add_alternative(html_body, subtype="html")

    return _send_message(
        message,
        mail_configuration=config,
    )


def send_test_email(
    *,
    recipient_email: str,
    mail_configuration: MailConfiguration | None = None,
) -> None:
    config = mail_configuration or mail_configuration_from_env()

    clean_recipient = str(recipient_email or "").strip()
    if not clean_recipient:
        raise EmailDeliveryError("Test recipient email is required.")

    message = EmailMessage()
    message["Subject"] = "AUGMIS email delivery test"
    message["From"] = formataddr(
        (config.from_name, config.from_email)
    )
    message["To"] = clean_recipient
    message.set_content(
        "AUGMIS email delivery is configured and working."
    )
    message.add_alternative(
        """<html><body style="font-family:Segoe UI,Arial,Helvetica,sans-serif;color:#17212b;"><h2>AUGMIS</h2><p>Email delivery is configured and working.</p></body></html>""",
        subtype="html",
    )

    _send_message(message, mail_configuration=config)
