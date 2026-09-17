# routed_common.sh - shared setup for the routed-peer topology's AP entrypoint
# (ap_entrypoint.sh). Sourced, not executed: sources ROS and resolves the RMW.
#
# Env: RMW_IMPLEMENTATION selects the RMW (set per role in gen_topology.sh's
# generated docker/compose/routed.yml).
set +u; source /opt/ros/jazzy/setup.bash; set -u

RMW="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
