from glob import glob

from setuptools import find_packages, setup

package_name = "urdf_raycast_sensors"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", glob("launch/*.launch.py")),
        (f"share/{package_name}/urdf", glob("urdf/*")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Workshop Team",
    maintainer_email="workshop@example.com",
    description="Analytic raycast range-sensor synthesis from URDF collision geometry.",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "laserscan_node = urdf_raycast_sensors.laserscan_node:main",
            "demo_mover = urdf_raycast_sensors.demo_mover:main",
            "pose_broadcaster = urdf_raycast_sensors.pose_broadcaster:main",
            "profile_node = urdf_raycast_sensors.profile_node:main",
        ],
    },
)
