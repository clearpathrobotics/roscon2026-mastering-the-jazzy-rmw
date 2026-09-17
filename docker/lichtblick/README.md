# Lichtblick with Pre-Installed Extensions

This directory builds a custom [Lichtblick](https://github.com/lichtblick-suite/lichtblick)
web image that ships with two joystick/teleop extensions already installed, so users
don't have to manually import `.foxe` files from the UI.

## Contents

| File | Purpose |
|------|---------|
| `Dockerfile.lichtblick_extensions` | Builds the custom image on top of the official Lichtblick web image. |
| `lcamero.joystick-extension-0.0.0.foxe` | Custom joystick teleop panel (publishes `geometry_msgs/msg/Twist` / `TwistStamped`). |
| `joshnewans.joy-panel-0.0.3.foxe` | Third-party Foxglove joystick/gamepad panel. |

## Build & Run

From **this directory** (`docker/lichtblick`):

```bash
# Build the image (build context = this directory, so the .foxe files are found)
docker build -f Dockerfile.lichtblick_extensions -t lichtblick-extensions .

# Run it
docker run -d --rm -p 8080:8080 --name lichtblick-extensions lichtblick-extensions

# Open the UI
#   http://localhost:8080
```

The extensions auto-install on the first page load and the page reloads once so the
panels appear immediately in the "Add panel" list.

## How the Dockerfile Works

The base image `ghcr.io/lichtblick-suite/lichtblick:latest` is the **web build** of
Lichtblick served by [Caddy](https://caddyserver.com/) as a static single-page app from
`/src`. Unlike the desktop app, the web build has no filesystem extension folder — it
loads extensions from the **browser's IndexedDB**. That's the core problem this Dockerfile
solves: how to get a `.foxe` into IndexedDB without the user manually importing it.

The build does three things:

### 1. Serve the `.foxe` files as static assets

```dockerfile
COPY --chmod=644 lcamero.joystick-extension-0.0.0.foxe \
    /www/extensions/lcamero.joystick-extension-0.0.0.foxe
COPY --chmod=644 joshnewans.joy-panel-0.0.3.foxe \
    /www/extensions/joshnewans.joy-panel-0.0.3.foxe
```

The two extension packages are copied into `/www/extensions/`. The entrypoint later
symlinks that folder into the web root (`/src/extensions`) so Caddy serves them at
`http://<host>:8080/extensions/...`.

### 2. Override the entrypoint to patch `index.html`

A heredoc (`COPY <<'ENTRYPOINT_SH' /entrypoint.sh`) writes a shell script that runs
every time the container starts. It does two patches to the served `index.html`:

- **Default-layout injection** — replicates the base image's behaviour of substituting
  the `LICHTBLICK_SUITE_DEFAULT_LAYOUT_PLACEHOLDER` token (kept so we don't lose the
  original startup behaviour when we overwrite `index.html`).
- **Auto-install script injection** — inserts an inline `<script>` just before `</body>`.

### 3. The auto-install script (runs in the browser)

On first page load, the injected JavaScript:

1. Opens the IndexedDB database `lichtblick-extensions-local` (the store Lichtblick's
   `IdbExtensionStorage` uses for the `local` namespace), creating the `metadata` and
   `extensions` object stores if needed.
2. For each extension, checks the `metadata` store to see if it's **already installed**
   (so a reload never re-installs).
3. If not installed, `fetch()`es the `.foxe` from `/extensions/...`, reads it as an
   `ArrayBuffer`, and writes two records:
   - the extension **info/metadata** into the `metadata` store, and
   - the info + raw **bytes** into the `extensions` store.
4. If anything was newly installed, it sets a `sessionStorage` flag and calls
   `location.reload()` **once** so Lichtblick picks up the new panels.

Because the "already installed" check is keyed on the extension `id` in the `metadata`
store, subsequent loads are no-ops and the page does not reload in a loop.

## Adding More Extensions

1. Copy the new `.foxe` into this directory.
2. Add a `COPY` line for it in the Dockerfile.
3. Add a new entry to the `EXTENSIONS` array in the entrypoint's auto-install script,
   filling in the `url` (must match the `/www/extensions/...` path) and the `info`
   fields (`id`, `name`, `publisher`, `version`, `namespace: "local"`, etc.).
4. Rebuild the image.

> **Note:** The `info.id` must be unique and stable — it's the key used for the
> "already installed" check. Changing it will cause the extension to be re-installed.
