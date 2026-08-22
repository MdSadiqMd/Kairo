module github.com/MdSadiqMd/Kairo

go 1.24

// The default build is standard-library only, so `go build ./...` and
// `go test ./...` run offline in CI without a module cache. Production AWS
// adapters (Kinesis source, S3 sink) live in files guarded by the `aws` build
// tag and pull the aws-sdk-go-v2 modules when built with `-tags aws`.
