# Log ingestor image. Built from the repo root.
# The default module is standard-library only so CI builds offline; the
# PRODUCTION binary needs the Kinesis/S3 adapters behind the `aws` build tag,
# so we pull the aws-sdk-go-v2 modules here and build with `-tags aws`.
FROM golang:1.24-bookworm AS build

WORKDIR /src
COPY . .

# Add the SDK modules (kept out of the checked-in go.mod on purpose) and build
# the aws-tagged binary. Static, so it runs on a distroless base.
RUN go get \
      github.com/aws/aws-sdk-go-v2/aws@latest \
      github.com/aws/aws-sdk-go-v2/config@latest \
      github.com/aws/aws-sdk-go-v2/service/kinesis@latest \
      github.com/aws/aws-sdk-go-v2/service/s3@latest \
 && CGO_ENABLED=0 GOOS=linux go build -tags aws -trimpath \
      -ldflags="-s -w" -o /out/log_ingestor ./services/log_ingestor

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/log_ingestor /log_ingestor
USER nonroot:nonroot
ENTRYPOINT ["/log_ingestor"]
