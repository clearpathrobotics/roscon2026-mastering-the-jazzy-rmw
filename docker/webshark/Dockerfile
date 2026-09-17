# Builds for amd64 and arm64. amd64 is still the validated workshop target. arm64 covers
# Apple Silicon laptops and Jetson-based robot computers.
#
# Builds on qxip/webshark (Node.js frontend + sharkd) but upgrades sharkd to
# Wireshark 4.6 (required by zenoh-dissector 1.9.0) and patches the sharkd
# communication module to bridge the old 3.x API format to 4.x JSON-RPC 2.0.
#
# Also includes Python + matplotlib/pandas so tshark/plot_capture.py can run inside
# this container without any host-side tools.
#
# Wireshark is installed once, in `base`, and every later stage derives from it. An earlier
# two-stage split installed it twice, the two installs resolved different PPA versions, and
# the zenoh plugin landed in a directory the running Wireshark never read. Do not add a
# second `apt-get install wireshark-*` to any stage below.

ARG TARGETARCH

# Vendored frontend, pinned to amd64 because upstream publishes no other manifest. Nothing
# in this stage runs and the tree it provides is JavaScript with no native objects, so an
# arm64 host can pull it without binfmt or emulation. Keep it free of RUN steps.
#
# The digest pins the licence as well as the code. This snapshot is GPL-2.0-or-later; current
# node-webshark is AGPL-3.0. Bumping it takes on AGPL section 13, which obliges anyone serving
# the viewer over a network to offer source to its users. Update THIRD-PARTY.md, the root
# LICENSE exceptions block and the three file headers if you ever move it.
ARG WEBSHARK_SRC_PLATFORM=linux/amd64
FROM --platform=${WEBSHARK_SRC_PLATFORM} qxip/webshark@sha256:2a4de07772d566f910418e87014f58da379f696a55b874fb685d174cfb6ca349 AS webshark_src

FROM ubuntu:24.04@sha256:786a8b558f7be160c6c8c4a54f9a57274f3b4fb1491cf65146521ae77ff1dc54 AS base
ARG DEBIAN_FRONTEND=noninteractive

# Node.js 20 LTS
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Wireshark from the official PPA. Not version-pinned: Launchpad's wireshark-dev/stable
# only publishes one version per series at a time, so a hard pin risks the build
# breaking outright once superseded. Instead, assert the ABI-relevant major.minor below
# and fail loudly on a future incompatible bump.
#
# install-setuid preseeded true so dumpcap gets setcap'd for non-root capture
# (cap_net_raw,cap_net_admin) instead of prompting interactively, which
# DEBIAN_FRONTEND=noninteractive would otherwise just skip.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        software-properties-common curl ca-certificates unzip gnupg \
    && add-apt-repository ppa:wireshark-dev/stable \
    && apt-get update \
    && echo "wireshark-common wireshark-common/install-setuid boolean true" | debconf-set-selections \
    && apt-get install -y --no-install-recommends \
        wireshark-common tshark \
    && rm -rf /var/lib/apt/lists/*

# The plugin is ABI-tied to the EPAN major.minor, so assert it here rather than in one
# of the arch branches, and fail loudly on a future incompatible bump.
RUN SHARK_MAJOR_MINOR=$(tshark --version 2>&1 | grep -oP '(?<=TShark \(Wireshark\) )\d+\.\d+') \
    && test "$SHARK_MAJOR_MINOR" = "4.6"

# The zenoh dissector, resolved per architecture. Upstream has only ever published a release
# binary for x86_64 Linux, so arm64 builds its own. Both branches leave the result at
# /out/libzenoh_dissector.so.

FROM base AS dissector-amd64
ARG ZENOH_DISSECTOR_VER=1.9.0
RUN mkdir -p /out \
    && curl -fsSL \
        "https://github.com/eclipse-zenoh/zenoh-dissector/releases/download/${ZENOH_DISSECTOR_VER}/x86_64-unknown-linux-gnu.zip" \
        -o /tmp/zenoh.zip \
    && echo "e79440bc9c8f4338f42a581cf2bbdb3d215cf6c03538a7e856866b7cdc547c20  /tmp/zenoh.zip" | sha256sum -c - \
    && unzip /tmp/zenoh.zip libzenoh_dissector.so -d /out \
    && rm /tmp/zenoh.zip

# Built from source, pinned to the commit behind tag 1.9.0 rather than the tag itself, so
# this path has provenance comparable to the amd64 checksum above.
#
# epan-sys ships a bindings.rs generated on x86_64 and uses it by default, and bindgen
# output encodes target type layout, so arm64 has to regenerate it. The feature has to be
# dependency-qualified because the workspace is virtual and a bare --features is rejected.
#
# libssl-dev is not in upstream's documented prerequisites, but openssl-sys (via
# zenoh-transport) fails to configure without it.
FROM base AS dissector-arm64
ARG DEBIAN_FRONTEND=noninteractive
ARG ZENOH_DISSECTOR_COMMIT=37c211002c830b5cf1bb5b1512d08941fca77edd
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git build-essential clang libclang-dev pkg-config libssl-dev \
        "wireshark-dev=$(dpkg-query -W -f='${Version}' wireshark-common)" \
    && rm -rf /var/lib/apt/lists/*
# Without this, epan-sys/build.rs quietly falls back to downloading and compiling the
# whole Wireshark source tarball instead of linking the one already installed.
RUN pkg-config --modversion wireshark
RUN curl -fsSL https://sh.rustup.rs | sh -s -- -y --default-toolchain stable --profile minimal
ENV PATH=/root/.cargo/bin:$PATH
RUN git clone https://github.com/eclipse-zenoh/zenoh-dissector /src \
    && git -C /src checkout "${ZENOH_DISSECTOR_COMMIT}" \
    && cd /src \
    && cargo build --release --locked -p zenoh-dissector --features epan-sys/bindgen \
    && mkdir -p /out \
    && cp target/release/libzenoh_dissector.so /out/

FROM dissector-${TARGETARCH} AS dissector

FROM base AS runtime
ARG DEBIAN_FRONTEND=noninteractive
COPY --from=dissector /out/libzenoh_dissector.so /tmp/libzenoh_dissector.so
# Globbed rather than computed from the multiarch triplet, because neither dpkg-architecture
# nor gcc is in this image. libwireshark has already created exactly one such directory.
RUN SHARK_MAJOR_MINOR=$(tshark --version 2>&1 | grep -oP '(?<=TShark \(Wireshark\) )\d+\.\d+') \
    && PLUGIN_DIR=$(ls -d /usr/lib/*/wireshark/plugins/"${SHARK_MAJOR_MINOR}"/epan) \
    && test "$(echo "${PLUGIN_DIR}" | wc -l)" = 1 \
    && mv /tmp/libzenoh_dissector.so "${PLUGIN_DIR}/" \
    && tshark -G plugins | grep -q libzenoh_dissector.so

# Non-root user for the app and for dumpcap (via the wireshark group, granted its
# capabilities above). Reuses ubuntu:24.04's built-in `ubuntu` user (UID 1000) rather
# than creating a new one. The README covers the override for a real robot whose host
# user has a different UID.
RUN usermod -aG wireshark ubuntu

# Python + plotting deps for tshark/plot_capture.py (no host tools needed).
# iproute2 is here for `ip -o -4 addr show`, which is how both the guide and the README
# tell you to pick a capture interface by address rather than by name. Without it that
# instruction dead-ends inside the container.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 python3-matplotlib python3-pandas iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Web app from qxip/webshark (frontend + Node API, sharkd resolved via PATH).
COPY --from=webshark_src /usr/src/node-webshark /usr/src/node-webshark

# Drop the upload route. fastify-autoload wires api/services/*.js by directory scan, so
# deleting the file is enough; nothing else in the tree references it. Workshop attendees
# are never taught to use it (fixtures arrive via `cp`), and it's a public write with no
# auth on a port bound to every interface, backed by an unmaintained fastify-file-upload
# dependency chain (busboy/dicer). This is that route's only reachable entry point.
RUN test -f /usr/src/node-webshark/api/services/upload.js
RUN rm /usr/src/node-webshark/api/services/upload.js

# The upload form itself: no route left to submit it to, and index.html no longer links
# to it (see the frontend patch below and index.html's own comment at the same spot).
RUN test -f /usr/src/node-webshark/web/upload.html
RUN rm /usr/src/node-webshark/web/upload.html

# fastify-file-upload and the busboy/dicer chain it pulls in exist only for the route just
# removed above (confirmed: `npm ls` shows fastify-file-upload as their sole dependent, and
# nothing outside api/services/upload.js required them). Deleting the packages rather than
# just the route means the 26 npm-audit advisories that chain carries can't come back
# reachable if a future edit re-adds a route that happens to require() one of them.
RUN test -d /usr/src/node-webshark/api/node_modules/fastify-file-upload
RUN rm -rf /usr/src/node-webshark/api/node_modules/fastify-file-upload \
           /usr/src/node-webshark/api/node_modules/express-fileupload \
           /usr/src/node-webshark/api/node_modules/busboy \
           /usr/src/node-webshark/api/node_modules/dicer

# Frontend patch: webshark_load_frame set Follow-Stream hrefs only for fol[i]
# with i>=1, so a single-follow capture (lab8 fol=[["UDP",...]]) showed no link.
RUN test "$(grep -c 'var i = 1; i < fol.length' /usr/src/node-webshark/web/js/webshark-app.js)" = 1
RUN sed -i 's/var i = 1; i < fol.length/var i = 0; i < fol.length/' /usr/src/node-webshark/web/js/webshark-app.js

# Frontend patch: file list sorts newest-first among otherwise-equal (dir/online-status) entries,
# so the current rotating window or streaming capture is always easy to find without parsing names.
RUN test "$(grep -c "return a\['name'\] > b\['name'\] ? 1 : -1;" /usr/src/node-webshark/web/js/webshark-app.js)" = 1
RUN sed -i "s/return a\['name'\] > b\['name'\] ? 1 : -1;/return (b['mtime']||0) - (a['mtime']||0) || (a['name'] > b['name'] ? 1 : -1);/" /usr/src/node-webshark/web/js/webshark-app.js

# Frontend patch: Webshark.prototype.update's intervals callback never checked data['err'],
# so a bad display filter's clean backend message ({"err":1,"errstr":"..."}) was silently
# dropped and the view just went stale/blank. Surface it on the filter box itself, and also
# run it through describe_capture() so a preset or typed filter against a capture that has
# vanished underneath the page reads the same way clicking Refresh already does ("can no
# longer be opened") instead of leaving the title bar's stale frame count standing next to
# a red box whose only explanation is sharkd's raw errstr.
RUN test "$(grep -c 'if (g_webshark_interval && that.status)' /usr/src/node-webshark/web/js/webshark-app.js)" = 1
RUN sed -i "s/if (g_webshark_interval && that.status)/if (data['err']) { document.getElementById('display_filter').style.border = '2px solid red'; document.getElementById('display_filter').title = data['errstr']; describe_capture(data); return; } document.getElementById('display_filter').style.border = ''; document.getElementById('display_filter').title = ''; if (g_webshark_interval \&\& that.status)/" /usr/src/node-webshark/web/js/webshark-app.js

# The three files below are modified GPL-2.0-or-later sources, so the image carries the
# statement of changes next to upstream's own LICENSE. Their headers point at this path.
COPY THIRD-PARTY.md /usr/src/node-webshark/THIRD-PARTY.md

# Patch sharkd communication module to speak JSON-RPC 2.0 (sharkd 4.x).
COPY sharkd_dict.js /usr/src/node-webshark/api/custom_module/sharkd_dict.js

# Full-file override: adds mtime to the files listing so the frontend can sort newest-first,
# plus a per-fixture description for the file list's Description column.
COPY root.js /usr/src/node-webshark/api/services/root.js
COPY fixtures/descriptions.tsv /usr/src/node-webshark/api/services/fixture-descriptions.tsv

# Full-file override. What it adds over stock webshark:
#   - a manual Refresh control and a prominent frame count, for live captures
#   - a border on the Endpoints/Statistics toolbar, which upstream leaves invisible
#   - a capture-level badge naming the RMW vendor and counting repair events
#   - RMW preset buttons (SPDP, SEDP, Zenoh Declare, Retransmits) with a toggle for
#     whether a preset filters the packet list or draws a rate graph
#   - Clear Graphs, since stock WSIOGraph can add rows but never drop them
#   - a readable Advanced graph: named series in the legend instead of "Graph #N",
#     a selectable bucket width (sharkd defaults to 1 s, which hides discovery
#     bursts entirely), a second Y axis, and zoom
#   - a ?graph= URL param to deep-link an Advanced Graph line
COPY index.html /usr/src/node-webshark/web/index.html

# The standalone field guide, reachable from the Guide link next to the capture badge. Shipped
# in the image rather than linked to GitHub so it works without a network and always describes
# the build actually running.
COPY guide.html /usr/src/node-webshark/web/guide.html
COPY guide-assets /usr/src/node-webshark/web/guide-assets

# sharkd colours frames server-side and webshark paints bg/fg onto the row. Stock Wireshark
# colours by transport, which leaves discovery, data and repair all the same shade. This is
# sharkd's personal profile, found without a -C flag because HOME is /home/ubuntu.
COPY --chown=ubuntu:ubuntu colorfilters /home/ubuntu/.config/wireshark/colorfilters

RUN chown -R ubuntu:ubuntu /usr/src/node-webshark

# Orientation for anyone who shells in. WORKDIR below is the app's directory, which has a
# sample captures/ next to it that is not the mount, so the first guess is usually wrong.
COPY shell-hint.sh /usr/local/bin/webshark-shell-hint
RUN chmod 0755 /usr/local/bin/webshark-shell-hint \
    && printf '\n# Orientation banner for interactive shells (docker exec -it ... bash).\ncase $- in *i*) /usr/local/bin/webshark-shell-hint ;; esac\n' \
       >> /etc/bash.bashrc

# The capture helper drives the host's docker CLI, so it cannot run in here. It ships anyway
# because guide.html does, and README.md does not: a deployment that never cloned the repo
# lifts it out with `docker cp webshark:/usr/local/bin/capture-robot.sh .`.
COPY capture-robot.sh /usr/local/bin/capture-robot.sh
RUN chmod 0755 /usr/local/bin/capture-robot.sh

WORKDIR /usr/src/node-webshark/api
ENV CAPTURES_PATH=/captures/
ENV SHARKD_SOCKET=/home/ubuntu/sharkd.sock
EXPOSE 8085

USER ubuntu
CMD ["npm", "start"]
