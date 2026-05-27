from glob import glob

from setuptools import find_packages, setup


package_name = "medicine_box"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/config", glob("config/*.yaml")),
        (f"share/{package_name}/doc", glob("doc/*.md")),
        (f"share/{package_name}/launch", glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools", "PyYAML"],
    zip_safe=True,
    maintainer="pan",
    maintainer_email="pan@example.com",
    description="Servo driven medicine box node for dispensing bound medicines.",
    license="MIT",
    entry_points={
        "console_scripts": [
            "medicine_box_node = medicine_box.medicine_box_node:main",
        ],
    },
)
