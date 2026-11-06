from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.core.tenant import TenantScope, get_scope
from app.services import email as email_service

router = APIRouter(prefix="/support", tags=["support"])

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_MESSAGE_CHARS = 5000


@router.post("/ticket")
async def create_support_ticket(
    message: str = Form(...),
    attachment: UploadFile | None = File(default=None),
    scope: TenantScope = Depends(get_scope),
):
    body = message.strip()
    if not body:
        raise HTTPException(422, "Message is required")
    if len(body) > MAX_MESSAGE_CHARS:
        raise HTTPException(422, f"Message max length is {MAX_MESSAGE_CHARS} characters")

    attachment_bytes: bytes | None = None
    attachment_filename: str | None = None
    attachment_content_type: str | None = None
    if attachment is not None and attachment.filename:
        attachment_bytes = await attachment.read(MAX_ATTACHMENT_BYTES + 1)
        if len(attachment_bytes) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(413, "Attachment max size is 5 MB")
        attachment_filename = Path(attachment.filename).name[:180] or "attachment"
        attachment_content_type = attachment.content_type or "application/octet-stream"

    sent = email_service.send_support_report_email(
        from_user_email=scope.user.email,
        tenant_id=scope.tenant_id,
        message=body,
        attachment_filename=attachment_filename,
        attachment_content_type=attachment_content_type,
        attachment_bytes=attachment_bytes,
    )
    if not sent:
        raise HTTPException(502, "Support email could not be sent")

    return {"status": "ok"}
