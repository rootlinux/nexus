FROM python:3.11-slim
WORKDIR /app
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
