from glob import glob

from setuptools import find_packages, setup


package_name = "task_manager"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/config", glob("config/*.yaml")),
        (f"share/{package_name}/launch", glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools", "PyYAML"],
    zip_safe=True,
    maintainer="pan",
    maintainer_email="pan@example.com",
    description="Minimal task manager demo for elderly companion robot task execution.",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "task_manager_node = task_manager.task_manager_node:main",
        ],
    },
)
