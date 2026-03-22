# syntax=docker/dockerfile:1

# ── Build stage ────────────────────────────────────────────────────────────────
FROM golang:1.23-alpine AS builder

WORKDIR /src

# Cache dependency downloads separately from source changes.
COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -o /raftd ./cmd/raftd

# ── Runtime stage ──────────────────────────────────────────────────────────────
FROM alpine:3.19

# wget is used by the Docker healthcheck.
RUN apk add --no-cache ca-certificates wget

COPY --from=builder /raftd /raftd

# QUIC (UDP) transport port + HTTP API port.
EXPOSE 7001/udp 8001/tcp

ENTRYPOINT ["/raftd"]
