FROM python:3.13-slim@sha256:eb43ff125d8d58d7449dcba7d336c23bcac412f526d861db493b9994d8010280

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/app/services/volume_archive_service.py /usr/local/lib/python3.13/site-packages/nukelab_volume_archive.py
COPY services/volume-helper/helper.py /app/helper.py
RUN mkdir /source /target /artifact /archive && chown 65532:65532 /source /target /artifact /archive
USER 65532:65532
ENTRYPOINT ["python", "-I", "/app/helper.py"]
