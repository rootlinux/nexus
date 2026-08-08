# Base image is digest-pinned so a rebuild resolves to the exact bytes this was
# tested against; the tag is kept for legibility and Dependabot refreshes the digest.
FROM python:3.11-slim@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff
WORKDIR /app
# Runtime dependencies only. requirements-dev.txt (pytest, httpx, ruff) is
# deliberately not installed here — test tooling has no business in a
# production image's attack surface.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN addgroup --system app \
    && adduser --system --ingroup app app \
    && mkdir -p /app/uploads /app/feedback_private_uploads \
    && chown -R app:app /app/uploads /app/feedback_private_uploads
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
