from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'person_tracker'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'),
         glob('launch/*.launch.py')),
    ],
    scripts=[
        'scripts/person_tracker_node.py',
        'scripts/person_tracker_bpu_node.py',
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='ubuntu',
    maintainer_email='ubuntu@todo.todo',
    description='Person detection and tracking with depth camera',
    license='TODO',
    tests_require=['pytest'],
)
