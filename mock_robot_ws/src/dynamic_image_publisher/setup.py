from glob import glob

from setuptools import find_packages, setup

package_name = "dynamic_image_publisher"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", glob("launch/*.launch.py")),
        (f"share/{package_name}/assets/sprites", glob("assets/sprites/*")),
        (f"share/{package_name}/assets/world", glob("assets/world/*")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Workshop Team",
    maintainer_email="workshop@example.com",
    description=(
        "Top-down world view with the robot's pre-rendered sprite overlaid at its "
        "tf2 pose, published as a dynamic camera image stream."
    ),
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "dynamic_image_node = dynamic_image_publisher.dynamic_image_node:main",
            "profile_node = dynamic_image_publisher.profile_node:main",
        ],
    },
)
