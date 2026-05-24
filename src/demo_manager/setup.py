from glob import glob

from setuptools import find_packages, setup


package_name = "demo_manager"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/doc", glob("doc/*.md")),
        (f"share/{package_name}/launch", glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="pan",
    maintainer_email="pan@example.com",
    description="High-level demo flow orchestrator for the elderly companion robot.",
    license="MIT",
    entry_points={
        "console_scripts": [
            "demo_manager_node = demo_manager.demo_manager_node:main",
        ],
    },
)
