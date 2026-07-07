from email import message_from_bytes                                                                                                                                                                                                          
from aiosmtpd.controller import Controller
from database.database import DBConnection
import logging
import os

log = logging.getLogger(__name__)

class MailHandler:
    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server, session, envelope):
        msg = message_from_bytes(envelope.content)
        subject = msg.get("subject", "")
        body = _extract_body(msg)

        with DBConnection() as db:
            for recipient in envelope.rcpt_tos:
                db.add_email(
                    to_address=recipient.lower(),
                    from_address=envelope.mail_from,
                    subject=subject,
                    body=body,
                )

        return "250"


def _extract_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in part.get("Content-Disposition", ""):
                return part.get_payload(decode=True).decode("utf-8", errors="replace")
        for part in msg.walk():
            if part.get_content_type() == "text/html" and "attachment" not in part.get("Content-Disposition", ""):
                return part.get_payload(decode=True).decode("utf-8", errors="replace")
    
    payload = msg.get_payload(decode=True)
    if payload:
        return payload.decode("utf-8", errors="replace")
    
    return ""


def startServer() -> Controller:
    hostname = "0.0.0.0"

    if os.name == "nt":
        hostname = "127.0.0.1"

    controller = Controller(MailHandler(), hostname=hostname, port=25)
    controller.start()
    log.info(f"SMTP server listening on {hostname}:25")
    return controller