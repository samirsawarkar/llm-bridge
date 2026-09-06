#!/usr/bin/env python3
from setuptools import setup, find_packages

setup(
    name="antigravity-bridge",
    version="1.0.0",
    description="Connect OpenClaw and Hermes to Google Antigravity OAuth session via local OpenAI proxy",
    long_description=open("README.md", encoding="utf-8").read() if open("README.md").readable() else "",
    long_description_content_type="text/markdown",
    author="Antigravity Bridge Contributors",
    license="MIT",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.8",
    install_requires=[],
    entry_points={
        "console_scripts": [
            "antigravity-bridge=antigravity_bridge.cli:main",
            "agy-bridge=antigravity_bridge.cli:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS",
    ],
)
