from setuptools import find_packages, setup

package_name = 'Mvc_sorting'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', ['config/hsv_colors.json']),
        ('share/' + package_name + '/launch',
            ['launch/color_sorting.launch.py']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='vovl773',
    maintainer_email='3152398081@qq.com',
    description='HSV colour blob detection and ROS 2 colour target publisher',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'Mvc_sorting_server = Mvc_sorting.Mvc_sorting_server:main',
            'Mvc_sorting_client = Mvc_sorting.Mvc_sorting_client:main',
        ],
    },
)
