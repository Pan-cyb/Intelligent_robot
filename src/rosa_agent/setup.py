from setuptools import find_packages, setup


package_name = "rosa_agent"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", ["launch/demo_with_rviz.launch.py"]),
    ],
    install_requires=["setuptools", "requests"],
    zip_safe=True,
    maintainer="pan",
    maintainer_email="pan@example.com",
    description="ROSA agent CLI and voice CLI for the Intelligent_robot ROS2 workspace.",
    license="MIT",
    entry_points={
        "console_scripts": [
            "rosa_cli = rosa_agent.cli:main",
            "rosa_voice_cli = rosa_agent.voice_cli:main",
            "rosa_test_asr = rosa_agent.asr_test:main",
            "tts_node = rosa_agent.tts_node:main",
        ],
    },
)
