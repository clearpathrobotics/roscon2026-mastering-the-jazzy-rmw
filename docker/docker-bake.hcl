variable "REGISTRY" {
  default = ""
}

variable "TAG" {
  default = "latest"
}

variable "SOURCE_URL" {
  default = "https://github.com/clearpathrobotics/roscon2026-mastering-the-jazzy-rmw"
}

variable "REVISION" {
  default = ""
}

variable "VERSION" {
  default = ""
}

variable "CREATED" {
  default = ""
}

function "tag" {
  params = [name]
  result = REGISTRY != "" ? ["${REGISTRY}/roscon2026-mastering-the-jazzy-rmw:${name}-${TAG}", "${REGISTRY}/roscon2026-mastering-the-jazzy-rmw:${name}-latest"] : ["ghcr.io/clearpathrobotics/roscon2026-mastering-the-jazzy-rmw:${name}-latest"]
}

function "labels" {
  params = []
  result = {
    "org.opencontainers.image.source"        = SOURCE_URL
    "org.opencontainers.image.documentation" = "${SOURCE_URL}#readme"
    "org.opencontainers.image.revision"      = REVISION
    "org.opencontainers.image.version"       = VERSION
    "org.opencontainers.image.created"       = CREATED
  }
}

group "default" {
  targets = ["ubuntu-headless", "webshark", "netdata", "lichtblick"]
}

target "ubuntu-headless" {
  context    = "."
  contexts   = {
    # mock robot workspace packages are prebuilt into the image (see the
    # Dockerfile's `COPY --from=mock_ws`); the workspace lives at the repo root,
    # so we add it as a named build context rather than moving the build root.
    mock_ws = "../mock_robot_ws"
  }
  dockerfile = "ubuntu-headless/Dockerfile"
  platforms  = ["linux/amd64", "linux/arm64"]
  tags       = tag("ubuntu-headless")
  labels     = labels()
}

# The webshark viewer. arm64 compiles the zenoh dissector from source (the
# Dockerfile's dissector-arm64 stage), so this target is the slow one to build;
# amd64 downloads a prebuilt dissector.
target "webshark" {
  context    = "webshark"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64", "linux/arm64"]
  tags       = tag("webshark")
  labels     = labels()
}

# Netdata with the Lab 3 fleet charts and StatsD config baked in.
target "netdata" {
  context    = "netdata"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64", "linux/arm64"]
  tags       = tag("netdata")
  labels     = labels()
}

# Lichtblick with the joystick/joy-panel extensions and default layout baked in.
target "lichtblick" {
  context    = "lichtblick"
  dockerfile = "Dockerfile.lichtblick_extensions"
  platforms  = ["linux/amd64", "linux/arm64"]
  tags       = tag("lichtblick")
  labels     = labels()
}
