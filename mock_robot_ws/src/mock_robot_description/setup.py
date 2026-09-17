from glob import glob
from setuptools import find_packages, setup

package_name = "mock_robot_description"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/urdf", glob("urdf/*")),
        (f"share/{package_name}/meshes/a300", glob("meshes/a300/*.*")),
        (f"share/{package_name}/meshes/a300/drivetrain", glob("meshes/a300/drivetrain/*.*")),
        (f"share/{package_name}/meshes/a300/drivetrain/wheels", glob("meshes/a300/drivetrain/wheels/*")),
        (f"share/{package_name}/meshes/a300/attachments", glob("meshes/a300/attachments/*")),
        (f"share/{package_name}/meshes/r100", glob("meshes/r100/*.*")),
        (f"share/{package_name}/meshes/r100/wheels", glob("meshes/r100/wheels/*")),
        (f"share/{package_name}/meshes/j100", glob("meshes/j100/*.*")),
        (f"share/{package_name}/meshes/j100/wheels", glob("meshes/j100/wheels/*")),
        (f"share/{package_name}/meshes/j100/attachments", glob("meshes/j100/attachments/*")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Workshop Team",
    maintainer_email="workshop@example.com",
    description="URDF and mesh assets for the mock A300, R100 and J100 robots.",
    license="Apache-2.0",
)
