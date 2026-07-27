from fastapi import HTTPException, Request, UploadFile, status


class PayloadTooLargeError(HTTPException):
    def __init__(self, detail: str = "Uploaded file is too large.") -> None:
        super().__init__(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=detail)


def reject_by_content_length_hint(request: Request, *, limit: int) -> None:
    """Cheap early rejection when Content-Length is present and over limit.
    Never sufficient alone: the header can be absent or understated."""
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError:
            return
        if declared > limit:
            raise PayloadTooLargeError()


async def read_upload_within_limit(file: UploadFile, *, limit: int) -> bytes:
    """Reads at most limit+1 bytes and raises 413 if that byte is reached.
    Second-layer defense — RequestBodySizeLimitMiddleware is the primary control
    for multipart routes, since Starlette has already fully parsed (and, past
    spool_max_size, spooled to disk) the file part by the time this runs."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise PayloadTooLargeError()
        chunks.append(chunk)
    return b"".join(chunks)
