#!/usr/bin/env python3
from setuptools import setup, find_packages

setup(
    name="antigravity-bridge",
    version="1.0.0",
    description="Connect OpenClaw and Hermes to Google Antigravity OAuth session via local OpenAI proxy",
    long_description=open("README.md", encoding="utf-8").read() if open("README.md").readable() else "",
    long_description_content_type="text/markdown",
    author="Samir Sawarkar",
    author_email="samirsawarkars@gmail.com",
    url="https://github.com/samirsawarkar/antigravity-bridge",
    project_urls={
        "Documentation": "https://github.com/samirsawarkar/antigravity-bridge#readme",
        "Source": "https://github.com/samirsawarkar/antigravity-bridge.git",
        "Tracker": "https://github.com/samirsawarkar/antigravity-bridge/issues",
    },
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
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS :: MacOS X",
    ],
)
