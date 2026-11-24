ARG BASE_IMAGE=ubuntu:24.04
ARG ITERATIVE_BASE_IMAGE=ubuntu:24.04
FROM ${BASE_IMAGE} AS boot-media-builder
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git gcc make binutils libc6-dev liblzma-dev python3 \
    mtools xorriso isolinux syslinux-common \
    && rm -rf /var/lib/apt/lists/*
COPY tools/boot-media/ /build-tools/
RUN bash /build-tools/build.sh --output /boot-media

# Application-only development builds may reuse a previously verified PXEye
# runtime. This target leaves system packages, external tools and boot media
# untouched and replaces only the installed application.
FROM ${ITERATIVE_BASE_IMAGE} AS iterative
USER 0:0
COPY pyproject.toml README.md LICENSE /app/
COPY src/ /app/src/
COPY src/pxeye/ /tmp/pxeye-overlay/
RUN /opt/pxeye/bin/python -c 'import pathlib, shutil, site; source = pathlib.Path("/tmp/pxeye-overlay"); target = pathlib.Path(site.getsitepackages()[0]) / "pxeye"; shutil.rmtree(target); shutil.copytree(source, target); shutil.rmtree(source)' \
    && /opt/pxeye/bin/python -c 'import pxeye; print(pxeye.__version__)'
ARG VCS_REF=unknown
ARG VERSION=unknown
LABEL org.opencontainers.image.title="PXEye" \
      org.opencontainers.image.source="https://github.com/DaoCloud/PXEye" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="Apache-2.0"
USER 1000:1000
WORKDIR /app

FROM ${BASE_IMAGE}
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv openssh-client ipmitool ca-certificates libgcc-s1 xorriso mtools openssl sshpass skopeo \
    && rm -rf /var/lib/apt/lists/* \
    && (getent passwd 1000 >/dev/null || useradd --uid 1000 --create-home console)
COPY bin/nico-admin-cli /usr/local/bin/nico-admin-cli
COPY bin/grpcurl /usr/local/bin/grpcurl
COPY bin/helm /usr/local/bin/helm
COPY --from=boot-media-builder /boot-media/ /usr/share/pxeye/boot-media/x86_64/
COPY tools/import-oci-bundle.py /usr/local/bin/pxeye-import-oci-bundle
RUN chmod 0755 /usr/local/bin/pxeye-import-oci-bundle
COPY pyproject.toml /tmp/pxeye-build/pyproject.toml
RUN python3 -m venv /opt/pxeye \
    && python3 -c 'import tomllib; p=tomllib.load(open("/tmp/pxeye-build/pyproject.toml", "rb")); print("\n".join(p["build-system"]["requires"] + p["project"].get("dependencies", [])))' > /tmp/pxeye-build/requirements.txt \
    && /opt/pxeye/bin/pip install --no-cache-dir -r /tmp/pxeye-build/requirements.txt \
    && rm -rf /tmp/pxeye-build
COPY pyproject.toml README.md LICENSE /app/
COPY src/ /app/src/
RUN /opt/pxeye/bin/pip install --no-cache-dir --no-deps --no-build-isolation /app
ARG VCS_REF=unknown
ARG VERSION=unknown
LABEL org.opencontainers.image.title="PXEye" \
      org.opencontainers.image.source="https://github.com/DaoCloud/PXEye" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="Apache-2.0"
ENV PATH="/opt/pxeye/bin:$PATH"
USER 1000:1000
WORKDIR /app
EXPOSE 8080
ENV PYTHONUNBUFFERED=1
CMD ["pxeye"]
