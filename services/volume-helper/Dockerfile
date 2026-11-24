FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/* \
    && rm -rf /usr/local/lib/python3.13/site-packages/pip* \
    /usr/local/lib/python3.13/site-packages/setuptools* \
    /usr/local/lib/python3.13/site-packages/wheel* \
    /usr/local/bin/pip*
COPY backend/app/services/volume_archive_service.py /usr/local/lib/python3.13/site-packages/nukelab_volume_archive.py
COPY services/volume-helper/helper.py /app/helper.py
RUN mkdir /source /target /artifact /archive && chown 65532:65532 /source /target /artifact /archive
USER 65532:65532
ENTRYPOINT ["python", "-I", "/app/helper.py"]
