ARG BASE_IMAGE=ubuntu:24.04
FROM ${BASE_IMAGE}
ARG DEBIAN_FRONTEND=noninteractive
ARG VCS_REF=unknown
LABEL org.opencontainers.image.title="PXEye" \
      org.opencontainers.image.source="https://github.com/SSmallMonster/PXEye" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.licenses="Apache-2.0"
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv openssh-client ipmitool ca-certificates libgcc-s1 xorriso openssl sshpass \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home console
COPY bin/nico-admin-cli /usr/local/bin/nico-admin-cli
COPY bin/grpcurl /usr/local/bin/grpcurl
COPY pyproject.toml README.md LICENSE /app/
COPY src/ /app/src/
RUN python3 -m venv /opt/pxeye && /opt/pxeye/bin/pip install --no-cache-dir /app
ENV PATH="/opt/pxeye/bin:$PATH"
USER 1000:1000
WORKDIR /app
EXPOSE 8080
ENV PYTHONUNBUFFERED=1
CMD ["pxeye"]
