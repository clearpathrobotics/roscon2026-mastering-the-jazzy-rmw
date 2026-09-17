from glob import glob

from setuptools import find_packages, setup

package_name = "mock_sensor_tools"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", glob("launch/*.launch.py")),
        (f"share/{package_name}/images", glob("images/*")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Workshop Team",
    maintainer_email="workshop@example.com",
    description="Mock sensor playback tools for MCAP-driven simulation.",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "mock_sensor_node = mock_sensor_tools.mock_sensor_node:main",
        ],
    },
)
