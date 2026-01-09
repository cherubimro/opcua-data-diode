#!/usr/bin/env python3
"""
OPC UA Data Diode - Setup Script
Copyright (C) 2026 Alin-Adrian Anton <alin.anton@upt.ro>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from setuptools import setup, find_packages
import pathlib

# Read the contents of README file
here = pathlib.Path(__file__).parent.resolve()
long_description = (here / "README.md").read_text(encoding="utf-8")

setup(
    name="opcua-data-diode",
    version="1.0.3",
    author="Alin-Adrian Anton",
    author_email="alin.anton@upt.ro",
    description="Secure one-way data replication for OPC UA servers using UDP over hardware data diodes",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/cherubimro/opcua-data-diode",
    project_urls={
        "Bug Tracker": "https://github.com/cherubimro/opcua-data-diode/issues",
        "Source Code": "https://github.com/cherubimro/opcua-data-diode",
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Manufacturing",
        "Intended Audience :: Telecommunications Industry",
        "Intended Audience :: System Administrators",
        "Topic :: Security",
        "Topic :: System :: Networking",
        "Topic :: System :: Monitoring",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
        "Operating System :: POSIX :: Linux",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: MacOS",
    ],
    keywords="opcua, data-diode, security, scada, ot, industrial, cybersecurity, one-way, mirroring",
    packages=find_packages(exclude=["tests", "tests.*"]),
    python_requires=">=3.7",
    install_requires=[
        "asyncua>=1.1.5",
        "lz4",
        "cryptography",
        "Pillow",
        "pyperclip",
    ],
    extras_require={
        "dev": [
            "pytest>=6.0",
            "pytest-asyncio",
            "pytest-cov",
            "black",
            "flake8",
            "mypy",
        ],
        "docs": [
            "sphinx",
            "sphinx-rtd-theme",
        ],
    },
    entry_points={
        "console_scripts": [
            "opcua-sender=opcua_data_diode.cli.sender_auto:main",
            "opcua-receiver=opcua_data_diode.cli.receiver_auto:main",
            "opcua-sender-gui=opcua_data_diode.gui.sender_gui:main",
            "opcua-receiver-gui=opcua_data_diode.gui.receiver_gui:main",
            "opcua-sender-tui=opcua_data_diode.gui.sender_gui_ncurses:main",
            "opcua-receiver-tui=opcua_data_diode.gui.receiver_gui_ncurses:main",
        ],
    },
    package_data={
        "opcua_data_diode.gui": ["*.png"],
    },
    include_package_data=True,
    zip_safe=False,
    license="GPLv3",
)
