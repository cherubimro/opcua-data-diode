# OPC UA Data Diode

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.7+](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)

A secure, one-way data replication system for OPC UA servers using UDP over hardware data diodes. This solution enables safe mirroring of OPC UA data from high-security networks to lower-security networks without risk of reverse communication.

## Features

- ✅ **Auto-discovery** of OPC UA server structure (Variables, Objects, Methods)
- ✅ **Real-time data synchronization** with configurable subscription intervals
- ✅ **Hardware data diode compatible** (one-way UDP communication)
- ✅ **Optional compression** (zlib, lz4) for bandwidth optimization
- ✅ **Optional encryption** (AES-128-GCM, AES-256-GCM, ChaCha20-Poly1305)
- ✅ **Multiple interfaces**:
  - Graphical GUI (Tkinter - Windows/Linux/macOS)
  - Terminal GUI (ncurses - SSH/terminal access)
  - Command-line (headless operation)
- ✅ **Automatic clipboard** support for encryption key sharing
- ✅ **Structure change monitoring** and automatic resynchronization
- ✅ **Comprehensive logging** and statistics

## Architecture

```
┌─────────────────────┐         ┌──────────────┐         ┌─────────────────────┐
│   OPC UA Server     │◄────────┤   SENDER     ├────────►│  Hardware Data      │
│  (Source Network)   │  TCP    │   (Reader)   │   UDP   │     Diode           │
└─────────────────────┘         └──────────────┘         └──────────┬──────────┘
                                                                     │ One-way
                                                         ┌───────────▼──────────┐
                                                         │    RECEIVER          │
                                                         │    (Writer)          │
                                                         └──────────┬───────────┘
                                                                    │ TCP
                                                         ┌──────────▼───────────┐
                                                         │  Shadow OPC UA       │
                                                         │  Server              │
                                                         │  (Target Network)    │
                                                         └──────────────────────┘
```

## Use Cases

- **Industrial OT/IT separation**: Safely replicate process data from OT network to IT network
- **DMZ data access**: Provide read-only access to OPC UA data in demilitarized zones
- **Security compliance**: Meet air-gap requirements while maintaining data visibility
- **Remote monitoring**: Enable safe monitoring of critical infrastructure
- **Data archival**: Stream data to historians without reverse connectivity

## Quick Start

### Installation

```bash
# Install from PyPI
pip install opcua-data-diode

# Or install from source
git clone https://github.com/cherubimro/opcua-data-diode.git
cd opcua-data-diode
pip install -e .
```

### Configuration

1. **Generate encryption key** (sender side):
```bash
python3 -m opcua_data_diode.gui.sender_gui
# Click "Generate New Key" - key is automatically copied to clipboard
```

2. **Configure sender** (`sender_config.json`):
```json
{
  "opcua_server_url": "opc.tcp://192.168.1.100:4840",
  "udp_host": "192.168.2.100",
  "udp_port": 5555,
  "compression": {"enabled": true, "method": "lz4"},
  "encryption": {"enabled": true, "algorithm": "aes-256-gcm", "key": "YOUR_KEY_HERE"}
}
```

3. **Configure receiver** (`receiver_config.json`):
```json
{
  "udp_host": "0.0.0.0",
  "udp_port": 5555,
  "shadow_server_port": 4841,
  "encryption": {"enabled": true, "algorithm": "aes-256-gcm", "key": "YOUR_KEY_HERE"}
}
```

### Running

> **⚠️ IMPORTANT:** Always start the **RECEIVER** and the **real OPC UA Server** first, then start the **SENDER**. The sender requires both the receiver and the real OPC UA server to be running before it can establish the connection.

**Graphical Interface (Tkinter):**
```bash
# 1. Start RECEIVER first
opcua-receiver-gui

# 2. Then start SENDER
opcua-sender-gui
```

**Terminal Interface (ncurses):**
```bash
# 1. Start RECEIVER first
opcua-receiver-tui

# 2. Then start SENDER
opcua-sender-tui
```

**Command Line (headless):**
```bash
# 1. Start RECEIVER first
opcua-receiver receiver_config.json

# 2. Then start SENDER
opcua-sender sender_config.json
```

## GUI Features

### Graphical GUI (Tkinter)
- Cross-platform (Windows, Linux, macOS)
- Configuration editor with validation
- Red/green status indicators (clickable to start/stop)
- Password visibility toggle
- About dialog with GPL license

### Terminal GUI (ncurses)
- Perfect for SSH access or headless systems
- Interactive configuration editing
- Selection menus for algorithms and compression
- Keyboard shortcuts (S:Start, X:Stop, G:GenKey, F3:Save, Q:Quit)
- Real-time status updates

## Security Features

### Encryption Algorithms
- **AES-128-GCM**: Fast, secure (128-bit keys)
- **AES-256-GCM**: Slower, more secure (256-bit keys) - **RECOMMENDED**
- **ChaCha20-Poly1305**: Fastest, modern (256-bit keys)

All algorithms use AEAD (Authenticated Encryption with Associated Data) providing both confidentiality and integrity.

### Compression Methods
- **zlib**: Standard compression, good ratio (~50-70% reduction)
- **lz4**: Faster compression, lower ratio (~30-50% reduction)

Compression is applied before encryption.


## Statistics & Monitoring

The system generates detailed statistics files:

- `discovery_statistics.txt`: Node discovery summary
- `skip_statistics.txt`: Skipped nodes and reasons
- `sender_auto.log`: Sender runtime logs
- `receiver_auto.log`: Receiver runtime logs

## Requirements

### Software
- Python 3.7 or higher
- For Tkinter GUI: python3-tk (Linux) or bundled (Windows/macOS)
- For ncurses GUI: ncurses (pre-installed on Linux/macOS)
- For clipboard support: xclip or xsel (Linux)

### Network
- UDP connectivity between sender and receiver
- Firewall rules allowing UDP port (default: 5555)
- TCP connectivity from sender to OPC UA server
- TCP connectivity from clients to shadow server

### Hardware Data Diode (Optional)
Compatible with commercial data diodes from:
- Any unidirectional network device supporting UDP

## Performance

Tested with Prosys OPC UA Simulation Server (2443 nodes, 2023 variables):
- **~100ms** subscription interval
- **<5% CPU** usage on modern hardware (typical)
- **Bandwidth** (varies with data change rate and compression):
  - **~10-25 KB/s** with zlib compression (level 6, **default**)
  - **~15-30 KB/s** with lz4 compression (faster, optional)
  - Uncompressed bandwidth depends on data change frequency and payload size

**Note:** Actual bandwidth depends heavily on:
- Number of variables changing simultaneously
- Data change frequency (subscription interval)
- Variable data types and array sizes
- Network conditions and compression settings

## License

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

See [LICENSE](LICENSE) for details.

## Author

**Alin-Adrian Anton**
Email: alin.anton@upt.ro
Copyright (C) 2026

## Support

For issues, questions, or feature requests:
- Open an issue on [GitHub Issues](https://github.com/cherubimro/opcua-data-diode/issues)
- Email: alin.anton@upt.ro
- Review logs in `sender_auto.log` and `receiver_auto.log`

## Acknowledgments

- Built with [python-asyncua](https://github.com/FreeOpcUa/python-asyncua)
- Uses [cryptography](https://cryptography.io/) for encryption
- GUI built with Tkinter and ncurses

## Roadmap

- [ ] Web-based monitoring dashboard
- [ ] Prometheus metrics exporter
- [ ] Docker containers
- [ ] Kubernetes deployment examples
- [ ] HA/failover support
- [ ] Performance metrics collection
- [ ] MQTT bridge support

---

**Made for industrial cybersecurity**
