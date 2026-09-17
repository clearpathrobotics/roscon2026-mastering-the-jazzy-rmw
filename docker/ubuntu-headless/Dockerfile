FROM ubuntu:24.04@sha256:786a8b558f7be160c6c8c4a54f9a57274f3b4fb1491cf65146521ae77ff1dc54

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        locales curl gnupg2 ca-certificates \
    && locale-gen en_US en_US.UTF-8 \
    && update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

ENV LANG=en_US.UTF-8

RUN curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
        -o /usr/share/keyrings/ros-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
        http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" \
        > /etc/apt/sources.list.d/ros2.list

RUN apt-get update && apt-get install -y --no-install-recommends \
        ros-jazzy-ros-base \
        ros-jazzy-xacro \
        ros-jazzy-twist-mux \
        ros-jazzy-teleop-twist-joy \
        ros-jazzy-robot-state-publisher \
        ros-jazzy-ros2-control \
        ros-jazzy-ros2-controllers \
        ros-jazzy-robot-localization \
        ros-jazzy-demo-nodes-cpp \
        ros-jazzy-demo-nodes-py \
        ros-jazzy-action-tutorials-cpp \
        ros-jazzy-action-tutorials-interfaces \
        ros-jazzy-rmw-cyclonedds-cpp \
        ros-jazzy-rmw-fastrtps-cpp \
        ros-jazzy-rmw-zenoh-cpp \
        ros-jazzy-ros2bag \
        ros-jazzy-rosbag2-storage-mcap \
        ros-jazzy-tracetools \
        ros-jazzy-performance-test \
        ros-jazzy-image-publisher \
        ros-jazzy-image-transport \
        ros-jazzy-compressed-image-transport \
        ros-jazzy-foxglove-bridge \
        ros-jazzy-urdfdom-py \
        python3-matplotlib \
        python3-numpy \
        python3-psutil \
        python3-yaml \
        cyclonedds-tools \
        lttng-tools \
        python3-lttng \
        python3-colcon-common-extensions \
        iproute2 \
        htop iftop tcpdump iperf3 \
        traceroute mtr-tiny nmap ncat socat dnsutils ethtool iputils-ping \
        tshark \
        tmux vim nano less jq git openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Nav2 stack for mock_robot_nav2 (navigation, SLAM, AMCL, map server).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ros-jazzy-navigation2 \
        ros-jazzy-nav2-bringup \
        ros-jazzy-slam-toolbox \
    && rm -rf /var/lib/apt/lists/*

LABEL org.opencontainers.image.title="roscon2026-jazzy-rmw-ubuntu-headless"
LABEL org.opencontainers.image.description="ROS 2 Jazzy headless with Fast DDS, Cyclone DDS, Zenoh, and benchmarking tools. Ubuntu 24.04."
LABEL org.opencontainers.image.licenses="Apache-2.0"

ENV ROS_DOMAIN_ID=25
ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ENV CYCLONEDDS_URI=file:///cyclonedds.xml
ENV FASTRTPS_DEFAULT_PROFILES_FILE=/fastdds.xml
ENV ZENOH_SESSION_CONFIG_URI=/zenoh_session.json5

# Reuse Lab 1's generic multicast profiles for the shared workshop image.
COPY rmw_configuration/cyclone/default_cyclone.xml /cyclonedds.xml
COPY rmw_configuration/fast/default_fast.xml /fastdds.xml
COPY rmw_configuration/zenoh/default_zenoh.json5 /zenoh_session.json5

# --- mock robot workspace --------------------------------------------------
# Prebuild the mock robot packages so Lab 3's `mock` fleet workload doesn't
# colcon-build in every replica at startup (N=20 concurrent builds would thrash).
# Sourced from the `mock_ws` named build context (docker-bake.hcl `contexts` /
# docker-compose `additional_contexts` -> ../mock_robot_ws). The URDFs
# use mock_components/GenericSystem, so there is no C++ hardware plugin to build.
COPY --from=mock_ws src /mock_robot_ws/src
RUN . /opt/ros/jazzy/setup.sh \
    && cd /mock_robot_ws \
    && colcon build --packages-select \
        mock_sensor_tools \
        mock_robot_description \
        mock_robot_bringup \
        urdf_raycast_sensors \
        dynamic_image_publisher \
    && rm -rf /mock_robot_ws/build /mock_robot_ws/log

RUN echo "source /opt/ros/jazzy/setup.bash" >> /root/.bashrc \
    && echo "[ -f /mock_robot_ws/install/setup.bash ] && source /mock_robot_ws/install/setup.bash" >> /root/.bashrc

CMD ["bash"]
