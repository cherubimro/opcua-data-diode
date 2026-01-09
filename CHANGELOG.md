# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-01-09

### Added
- Initial release
- OPC UA server auto-discovery and structure mirroring
- Real-time data synchronization via UDP
- Hardware data diode compatibility
- Compression support (zlib, lz4)
- Encryption support (AES-128-GCM, AES-256-GCM, ChaCha20-Poly1305)
- Graphical GUI (Tkinter) for Windows/Linux/macOS
- Terminal GUI (ncurses) for SSH/terminal access
- Command-line interface for headless operation
- Automatic clipboard support for encryption key sharing
- Structure change monitoring and resynchronization
- Comprehensive logging and statistics
- Red/green status indicators (clickable)
- Configuration validation
- Password visibility toggle
- Algorithm and compression method selection menus
- GPL v3 license with About dialog
- Shadow OPC UA server URL display
- Key length validation based on algorithm

### Features
- Discovers 2000+ nodes automatically
- <5% CPU usage on modern hardware
- ~100ms subscription interval support
- 50-70% bandwidth reduction with compression
- AEAD encryption with integrity protection

### Documentation
- Comprehensive README.md

### Testing
- Tested with Prosys OPC UA Simulation Server
- 2427 nodes discovered and mirrored successfully
- 1591 nodes created, 47 skipped (permissions/errors)
- Verified on Linux (openSUSE)

## [Unreleased]

### Planned
- Web-based monitoring dashboard
- Prometheus metrics exporter
- Docker containers
- Kubernetes deployment examples
- HA/failover support
- Performance metrics collection
- MQTT bridge support
- Enhanced error recovery
- Multi-server support
- Data filtering/transformation

---

[1.0.0]: https://github.com/cherubimro/opcua-data-diode/releases/tag/v1.0.0
