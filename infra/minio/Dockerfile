FROM golang:1.25-alpine AS build
RUN apk add --no-cache git
ARG MINIO_RELEASE=RELEASE.2025-04-22T22-12-26Z
RUN git clone --depth 1 --branch "$MINIO_RELEASE" https://github.com/minio/minio.git /src
WORKDIR /src
RUN CGO_ENABLED=0 go build -trimpath -o /minio .

FROM alpine:3.22
RUN apk add --no-cache ca-certificates curl && adduser -D -u 1001 minio && mkdir /data && chown minio:minio /data
COPY --from=build /minio /usr/local/bin/minio
COPY --from=build /src/LICENSE /usr/share/doc/minio/LICENSE
LABEL org.opencontainers.image.source="https://github.com/minio/minio" org.opencontainers.image.licenses="AGPL-3.0"
USER minio
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
CMD ["server", "/data", "--console-address", ":9001"]
