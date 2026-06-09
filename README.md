# s3m-protobuild

Generate Go and Python packages, OpenAPI specs, and `FileDescriptorSet` files from S3M protobuf source repositories.

Builds one or more proto source repositories containing a `MODULE` file and a `proto/` tree. Use selectors to choose which packages and which output formats to produce.

Targets:

- `go`: a Go module rooted at the source's `GO_PACKAGE`, with `.pb.go` files (plus `.pb.gw.go` for any package that ships a `service.yaml`) and a generated `go.mod` (tidied via `go mod tidy`).
- `py`: a `grpcio`-based Python package with a `setup.py`, suitable for `pip install`.
- `pyb`: a [BetterProto](https://github.com/danielgtaylor/python-betterproto)-based Python package with a `setup.py`, suitable for `pip install`.
- `oas`: an `openapi.yaml` rendered via `protoc-gen-oas`.

`--descriptor-out` can be combined with any combination of targets to emit a protobuf `FileDescriptorSet` for everything selected.

---


## Install

```shell
pip install git+https://github.com/olcf/s3m-protobuild.git
```

If the resulting `s3m-protobuild` command isn't on your `PATH` (common when running `pip` outside an active venv), you can try:

```shell
uv tool install git+https://github.com/olcf/s3m-protobuild.git
```


## Quickstart: build an S3M-APIs Python package

```shell
mkdir /tmp/s3m-apis-pyb-build && cd /tmp/s3m-apis-pyb-build
s3m-protobuild setup python --venv .venv
s3m-protobuild build \
  --source git+https://github.com/olcf/s3m-apis.git@main \
  --venv .venv \
  --out ./s3m-apis-pyb \
  common:pyb status:pyb streaming:pyb
```

The `setup` command provisions a Python environment in `.venv/`. The `build` command clones `github.com/olcf/s3m-apis` and generates a BetterProto Python package containing the `common`, `status`, and `streaming` proto packages at `./s3m-apis-pyb`.

**Note:** `pyb` builds use `betterproto`, so client/server RPC calls must be async. See [Why prefer `pyb`](#why-prefer-pyb-betterproto-over-py-grpcio) to understand the tradeoffs.

## Quickstart: build an S3M-APIs Go module

```shell
mkdir /tmp/s3m-apis-go-build && cd /tmp/s3m-apis-go-build
s3m-protobuild setup python --venv .venv
s3m-protobuild setup go --go .go
s3m-protobuild build \
  --source git+https://github.com/olcf/s3m-apis.git@main \
  --venv .venv --go .go \
  --out ./s3m-apis-go \
  common:go status:go streaming:go
```

The two `setup` commands provision Python and Go environments in `.venv/` and `.go/`. The third command clones `github.com/olcf/s3m-apis` and generates a Go module containing the `common`, `status`, and `streaming` proto packages at `./s3m-apis-go`.


## Tiny client examples

### Python

```shell
cd /tmp/s3m-apis-pyb-build
python -m venv venv
source venv/bin/activate

pip install ./s3m-apis-pyb
export S3M_ENDPOINT=https://s3m.olcf.ornl.gov
export S3M_TOKEN=<...>
```

Create `test.py`:

```py
import asyncio
import os

from s3m_apis_betterproto.clientfactory import S3MClientFactory
from s3m_apis_betterproto.status import v1alpha

async def main():
    factory = S3MClientFactory(os.environ["S3M_ENDPOINT"], os.environ["S3M_TOKEN"])
    try:
        status = factory.create_client(v1alpha.StatusStub)
        resource = await status.get_resource(
            v1alpha.GetResourceRequest(resource_name="defiant")
        )
        print(resource)
    finally:
        factory.close()

asyncio.run(main())
```

Then run it:

```shell
python test.py
```

### Go

```shell
cd /tmp/s3m-apis-go-build
mkdir s3m-go-client && cd s3m-go-client

go mod init example.com/s3m-go-client
go mod edit -replace github.com/olcf/s3m-apis=../s3m-apis-go

export S3M_ENDPOINT=https://s3m.olcf.ornl.gov
export S3M_TOKEN=<...>
```

Create `main.go`:

```go
package main

import (
	"context"
	"log"
	"os"
	"time"

	"github.com/olcf/s3m-apis/pkg/s3mutil"
	status "github.com/olcf/s3m-apis/status/v1alpha"
)

func main() {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	conn, err := s3mutil.NewS3MConn(os.Getenv("S3M_ENDPOINT"), os.Getenv("S3M_TOKEN"))
	if err != nil {
		log.Fatal(err)
	}
	defer conn.Close()

	client := status.NewStatusClient(conn)
	resource, err := client.GetResource(ctx, &status.GetResourceRequest{
		ResourceName: "defiant",
	})
	if err != nil {
		log.Fatal(err)
	}
	log.Printf("%+v", resource)
}
```

Then resolve dependencies and run it:

```shell
go mod tidy
go run main.go
```

---


## System prereqs

`protoc` must already be in your `PATH`. To build Go packages, `go` must be in your `PATH`. `s3m-protobuild setup` will not install either. Run `s3m-protobuild env` to see anything missing and install hints.


## Setup helpers

`s3m-protobuild setup` installs the various required generator plugins. It only mutates local toolchain directories (`.go`, `.venv`, if specified), and never alters system Python/Go toolchains or dotfiles.

- `s3m-protobuild setup python --venv PATH`: creates the virtualenv at `PATH` if it doesn't exist, then installs the pinned Python generator dependencies into it.
- `s3m-protobuild setup go --go PATH`: installs the pinned Go protoc plugins into `PATH/bin`, keeping `GOPATH`, the module cache, and the build cache all under `PATH`.

Both subcommands can be invoked together: `s3m-protobuild setup python go --venv .venv --go .go`

---


## Building

```shell
s3m-protobuild build \
  --venv PATH --go PATH \
  --source SOURCE [--source SOURCE ...] \
  --out PATH \
  SELECTOR [SELECTOR ...]
```

* `--source` may be repeated to combine multiple proto repositories in one build (see [Multi-source builds](#multi-source-builds-and---go-mod-replace)).
* `--venv` and `--go` are only needed to reference local toolchains (like from `s3m-protobuild setup`).
* `--out` sets the output root and is always required. One or more selectors must be provided.
* Pass `--include-source` to copy `.proto` and `service.yaml` source files to the output alongside the generated code.
* Pass `--unsafe-overwrite` to let `build` replace a non-empty `--out` that wasn't produced by a previous `s3m-protobuild` run (as marked by `build.info`).


### Selectors

A selector has the shape `[MODULE/]package[/version]:target`. The four valid targets are `go`, `py`, `pyb`, and `oas`. A selector with no version is a *family* selector and expands to every `v*` subdirectory under the package; a selector with a version pins exactly that directory. `MODULE/` is only needed when the same proto package name exists in more than one `--source`.

```text
common:go                       # every v* directory under common, Go target
slurm/v0042:go                  # pin one version
slurm:py                        # all v* directories under slurm, grpcio Python
status:oas                      # OpenAPI spec from status
s3m-apis/streaming:go           # disambiguate when multiple sources expose `streaming`
```


### Sources

`--source` accepts either a local filesystem path or a `git+<scheme>://host/path[@REF]` URL (pip style). Remote sources are cloned into a temp directory that is removed when the build exits.

SSH `--source` example: `git+ssh://git@github.com/olcf/s3m-apis.git@main`


## MODULE file format

Every source root must contain a `MODULE` file, a simple `KEY=VALUE` config. Minimal example:

```
MODULE=s3m-apis
VERSION=0.1.0
GO_PACKAGE=github.com/olcf/s3m-apis
```

Required:

- `MODULE=`: lowercase kebab-case identifier
- `VERSION=`: `X.Y.Z` or `X.Y.ZrcN`
- `GO_PACKAGE=`: Go import path for `go` targets

Optional:

- `PY_PACKAGE=`: Python import name for the `py` (grpcio) target. Defaults to `<MODULE>_grpcio`.
- `PYB_PACKAGE=`: same, for `pyb` (BetterProto). Defaults to `<MODULE>_betterproto`.
- `FLATTEN_NAMESPACES=`: comma-separated dotted namespace paths to flatten into the package root (`pyb` only). Example: `FLATTEN_NAMESPACES=olcf.s3m` moves everything under `olcf/s3m/` to the package root.

Python packages use snake_case import paths and kebab-case distribution names. `s3m-protobuild` derives both forms from values of `MODULE=`, `PY_PACKAGE=`, and `PYB_PACKAGE=`.

---


## Output layout

`--out` sets the output root. After a build, a typical Go output looks like:

```text
./s3m-apis-go/
  build.info
  go.mod
  common/v1alpha/*.pb.go
  status/v1alpha/*.pb.go
  streaming/v1alpha/*.pb.go
```

And a BetterProto Python output:

```text
./s3m-apis-pyb/
  build.info
  setup.py
  s3m_apis_betterproto/
    __init__.py
    common/...
    status/...
```

Rules:

- You may not build `py` and `pyb` targets in the same call.
- Every `go`, `py`, and `pyb` build selector must resolve to the same source module (otherwise, generated module/package names would compete; `oas` outputs are exempt because OpenAPI specs are keyed by API paths).
- The `--out` root may not equal or sit inside any `--source` root.
- Output to `.git`, `.venv`/`venv`, `.go`/`go`, `proto`, `src`, `internal`, `s3m-protobuild`, and `s3m_protobuild` directories is disallowed for safety.

Every build writes a `build.info` manifest with build info and toolchain metadata. (`s3m-protobuild` also uses this as a marker to decide whether the directory is a previous output safe to overwrite.)


## Clean and rebuilds

```shell
s3m-protobuild clean --out ./s3m-apis-go
```

`clean` deletes the output root, but only if it contains a `build.info` marker, so it can't be pointed at an arbitrary directory. Rebuilds delete existing `--out` roots with `build.info` markers, so do not edit files in output roots or add new files to them! To allow outputting to an existing non-empty unmanaged directory (no `build.info` file), pass `--unsafe-overwrite`.

---


## Multi-source builds and `--go-mod-replace`

Sometimes it is necessary to reference protos from other repos. `s3m-protobuild` supports sourcing multiple proto repos to resolve cross-repo dependencies. This enables the OLCF internal/closed-source S3M APIs to import protos from the public/open-source S3M API repos, and allows you to write your own extension repos.

When building multiple S3M Go proto packages that rely on each other, generated `go.mod` files need `replace` directives that redirect the imported package's import path (e.g., `github.com/olcf/s3m-apis`) to a local path (e.g., `../s3m-apis/`). The `--go-mod-replace` flag can add these for you.

```shell
s3m-protobuild build \
  --venv .venv --go .go \
  --source git+https://github.com/olcf/s3m-apis.git@main \
  --out ./s3m-apis \
  common:go status:go streaming:go

s3m-protobuild build \
  --venv .venv --go .go \
  --source ../s3m-apis-myextensions \
  --source git+https://github.com/olcf/s3m-apis.git@main \
  --go-mod-replace github.com/olcf/s3m-apis=../s3m-apis \
  --out ./s3m-apis-myextensions \
  koas:go streamingadmin:go
```

`--go-mod-replace MODULE=PATH` adds a `replace MODULE => PATH` directive to the generated `go.mod`. `PATH` is written verbatim; Go resolves it relative to the generated `go.mod` (so `../s3m-apis` above means "next to `./s3m-apis-myextensions`"). The local replace is what makes the extension compile against the artifact you just generated rather than trying to pull the package (e.g., from `github.com/olcf/s3m-apis`). When `go mod tidy` complains about a missing import that another `--source` provides, `s3m-protobuild` will suggest a `--go-mod-replace` flag.

---


## Python packages

The `py` (grpcio) and `pyb` (BetterProto) targets produce installable distributions with a generated `setup.py`. The package import roots default to `<MODULE>_grpcio` (for `py`) and `<MODULE>_betterproto` (for `pyb`); set `PY_PACKAGE=` or `PYB_PACKAGE=` in your source's `MODULE` file to override.


## Why prefer `pyb` (BetterProto) over `py` (grpcio)

We recommend the `pyb` target for most users. BetterProto generates pure-Python dataclasses with full type hints; its messages can be constructed, read, and serialized like ordinary Python objects:

```python
from s3m_apis_betterproto.status import v1alpha

req = v1alpha.GetResourceRequest(resource_name="kestrel")
print(req.to_json())
```

The `py` target generates classes from `grpcio-tools`. Those classes are less ergonomic and Pythonic, and require `mypy-protobuf` stubs to type-check cleanly.

The main potential pain point of `pyb` is that it uses `grpclib` for transport, so generated service stubs are `asyncio`-first. Async can look daunting at first, but only client/server RPC calls need to be async; the rest of your application can stay synchronous.

`py` targets (using `grpcio`) are synchronous by default; async callers must opt in through its `grpc.aio` companion API.

BetterProto builds are pure Python with no C extension requirement. `py` targets require `grpcio`'s native runtime.

---


## OpenAPI and descriptors

The `oas` target writes a single `openapi.yaml` at the `--out` root. `--descriptor-out PATH` writes a `FileDescriptorSet` at `PATH` (relative to `--out`; absolute paths and `..` are rejected) covering every package that any selector resolved, regardless of which targets were requested.

`--descriptor-imports` and `--descriptor-source-info` pass `--include_imports` and `--include_source_info` through to `protoc`.

```shell
s3m-protobuild build \
  --venv .venv --go .go \
  --source git+https://github.com/olcf/s3m-apis.git@main \
  --out ./s3m-apis-specs \
  --descriptor-out s3m-apis.desc \
  --descriptor-imports \
  status:oas streaming:oas
```


## Diagnostics

`s3m-protobuild env` prints the discovered versions of every tool the builder calls, and emits a `To fix:` block with `s3m-protobuild setup` commands and OS package/toolchain hints. Pass `--venv` and `--go` to also check tools in local toolchains.

```shell
s3m-protobuild env [--venv .venv --go .go]
```

---


## License

Dual-licensed under the MIT License ([`LICENSE-MIT`](LICENSE-MIT)) or the Apache License 2.0 ([`LICENSE-APACHE`](LICENSE-APACHE)), at your option.
