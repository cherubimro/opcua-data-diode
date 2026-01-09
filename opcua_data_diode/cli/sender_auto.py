#!/usr/bin/env python3
"""
OPC UA Auto-Discovery Sender - Automatically discovers and streams entire OPC UA server
"""
import asyncio
import json
import socket
import logging
import zlib
import os
import base64
from datetime import datetime
from asyncua import Client
from asyncua import ua
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305

# Try to import lz4 for faster compression (optional)
try:
    import lz4.frame
    HAS_LZ4 = True
except ImportError:
    HAS_LZ4 = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AutoDiscoverySender:
    """Sender that auto-discovers and mirrors entire OPC UA server"""

    def __init__(self, config):
        # Support both old format {'sender': {...}} and new format with direct config
        if 'sender' in config:
            self.config = config['sender']
        else:
            self.config = config

        self.client = None
        self.udp_socket = None
        self.udp_address = None
        self.discovered_nodes = {}
        self.variable_nodes = []
        self.subscription = None

        # Compression settings
        self.compression_enabled = self.config.get('compression', {}).get('enabled', False)
        self.compression_method = self.config.get('compression', {}).get('method', 'zlib')
        self.compression_level = self.config.get('compression', {}).get('level', 6)

        # Validate compression settings
        if self.compression_enabled:
            if self.compression_method == 'lz4' and not HAS_LZ4:
                logger.warning("LZ4 compression requested but python-lz4 not installed. Falling back to zlib.")
                self.compression_method = 'zlib'
            logger.info(f"Compression enabled: {self.compression_method} (level {self.compression_level if self.compression_method == 'zlib' else 'N/A'})")

        # Encryption settings
        self.encryption_enabled = self.config.get('encryption', {}).get('enabled', False)
        self.encryption_algorithm = self.config.get('encryption', {}).get('algorithm', 'aes-256-gcm').lower()
        self.cipher = None
        self.algorithm_id = None

        if self.encryption_enabled:
            encryption_key = self.config.get('encryption', {}).get('key', '')
            if not encryption_key:
                logger.error("Encryption enabled but no key provided in config. Disabling encryption.")
                self.encryption_enabled = False
            else:
                try:
                    # Decode the base64 key
                    key_bytes = base64.b64decode(encryption_key)

                    # Initialize cipher based on algorithm
                    if self.encryption_algorithm == 'aes-128-gcm':
                        if len(key_bytes) != 16:
                            raise ValueError(f"AES-128-GCM requires 16-byte key, got {len(key_bytes)} bytes")
                        self.cipher = AESGCM(key_bytes)
                        self.algorithm_id = 0x01
                        logger.info("Encryption enabled: AES-128-GCM")
                    elif self.encryption_algorithm == 'aes-256-gcm':
                        if len(key_bytes) != 32:
                            raise ValueError(f"AES-256-GCM requires 32-byte key, got {len(key_bytes)} bytes")
                        self.cipher = AESGCM(key_bytes)
                        self.algorithm_id = 0x02
                        logger.info("Encryption enabled: AES-256-GCM")
                    elif self.encryption_algorithm == 'chacha20-poly1305':
                        if len(key_bytes) != 32:
                            raise ValueError(f"ChaCha20-Poly1305 requires 32-byte key, got {len(key_bytes)} bytes")
                        self.cipher = ChaCha20Poly1305(key_bytes)
                        self.algorithm_id = 0x03
                        logger.info("Encryption enabled: ChaCha20-Poly1305")
                    elif self.encryption_algorithm == 'fernet':
                        # Legacy support
                        self.cipher = Fernet(encryption_key.encode())
                        self.algorithm_id = 0x00
                        logger.info("Encryption enabled: Fernet (AES-128-CBC) - LEGACY, consider upgrading to GCM")
                    else:
                        raise ValueError(f"Unknown encryption algorithm: {self.encryption_algorithm}")

                except Exception as e:
                    logger.error(f"Invalid encryption configuration: {e}. Disabling encryption.")
                    self.encryption_enabled = False

        # Discovery statistics
        self.discovery_stats = {
            'total_nodes': 0,
            'by_node_class': {},
            'variables_with_read_errors': [],
            'variables_successfully_read': 0,
            'discovery_errors': []
        }

        # Runtime statistics for periodic logging
        self.runtime_stats = {
            'data_changes_sent': 0,
            'last_summary_time': None,
            'packets_sent': 0,
            'bytes_sent': 0
        }

    def _compress_payload(self, data):
        """Compress payload if compression is enabled"""
        if not self.compression_enabled:
            return data, False

        try:
            if self.compression_method == 'lz4':
                compressed = lz4.frame.compress(data)
            else:  # zlib
                compressed = zlib.compress(data, level=self.compression_level)

            # Only use compression if it actually reduces size
            if len(compressed) < len(data):
                return compressed, True
            else:
                return data, False
        except Exception as e:
            logger.warning(f"Compression failed: {e}, sending uncompressed")
            return data, False

    def _encrypt_payload(self, data):
        """Encrypt payload if encryption is enabled

        Args:
            data: bytes to encrypt

        Returns:
            tuple: (encrypted_bytes, algorithm_id) or (data, None) if encryption disabled/failed
        """
        if not self.encryption_enabled or not self.cipher:
            return data, None

        try:
            if self.algorithm_id == 0x00:
                # Fernet - handles everything internally
                encrypted = self.cipher.encrypt(data)
                return encrypted, self.algorithm_id
            else:
                # AEAD ciphers (GCM, ChaCha20-Poly1305)
                # Generate random 12-byte nonce
                nonce = os.urandom(12)
                # Encrypt (returns ciphertext + 16-byte auth tag)
                ciphertext = self.cipher.encrypt(nonce, data, None)
                # Prepend nonce to ciphertext
                encrypted = nonce + ciphertext
                return encrypted, self.algorithm_id
        except Exception as e:
            logger.error(f"Encryption failed: {e}, sending unencrypted")
            return data, None

    def _send_udp(self, payload_dict):
        """Send UDP packet with optional compression and encryption

        Protocol structure:
        [encryption_flag:1byte][algorithm_id:1byte if encrypted][encrypted/plain:[compression_flag:1byte][compression_method:1byte if compressed][data]]
        """
        try:
            # Convert to JSON
            json_data = json.dumps(payload_dict, default=str).encode('utf-8')

            # Compress if enabled
            data, is_compressed = self._compress_payload(json_data)

            # Wrap with compression indicator
            if is_compressed:
                # Prepend compression flag (1 byte) + method (1 byte)
                method_byte = b'\x01' if self.compression_method == 'lz4' else b'\x00'  # 0=zlib, 1=lz4
                inner_data = b'\x01' + method_byte + data  # First byte: 1=compressed
            else:
                inner_data = b'\x00' + data  # First byte: 0=uncompressed

            # Encrypt if enabled
            encrypted_data, algorithm_id = self._encrypt_payload(inner_data)
            if algorithm_id is not None:
                # Encrypted
                final_data = b'\x01' + bytes([algorithm_id]) + encrypted_data
            else:
                # Not encrypted
                final_data = b'\x00' + inner_data

            self.udp_socket.sendto(final_data, self.udp_address)

            # Track statistics
            self.runtime_stats['packets_sent'] += 1
            self.runtime_stats['bytes_sent'] += len(final_data)

            return len(final_data)
        except Exception as e:
            logger.error(f"Failed to send UDP packet: {e}")
            return 0

    def log_periodic_summary(self, force=False):
        """Log a summary of runtime statistics"""
        now = datetime.utcnow()

        if self.runtime_stats['last_summary_time'] is None:
            self.runtime_stats['last_summary_time'] = now
            return

        elapsed = (now - self.runtime_stats['last_summary_time']).total_seconds()

        # Only check every 30 seconds to reduce overhead
        if not force and elapsed < 30:
            return

        # Calculate rates
        packets_per_sec = self.runtime_stats['packets_sent'] / elapsed if elapsed > 0 else 0
        kb_per_sec = (self.runtime_stats['bytes_sent'] / 1024) / elapsed if elapsed > 0 else 0

        # Log summary
        logger.info(
            f"[STATS] {self.runtime_stats['data_changes_sent']} data changes | "
            f"{self.runtime_stats['packets_sent']} packets ({packets_per_sec:.1f}/s) | "
            f"{self.runtime_stats['bytes_sent']/1024:.1f} KB ({kb_per_sec:.1f} KB/s)"
        )

        # Reset counters
        self.runtime_stats['data_changes_sent'] = 0
        self.runtime_stats['packets_sent'] = 0
        self.runtime_stats['bytes_sent'] = 0
        self.runtime_stats['last_summary_time'] = now

    async def connect(self):
        """Connect to OPC UA server"""
        server_url = self.config['opcua_server_url']
        logger.info(f"Connecting to OPC UA server: {server_url}")

        self.client = Client(url=server_url)
        await self.client.connect()
        logger.info("Connected to OPC UA server")

        # Setup UDP
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_address = (
            self.config['udp_host'],
            self.config['udp_port']
        )

        # Initialize summary time
        self.runtime_stats['last_summary_time'] = datetime.utcnow()

    async def discover_nodes(self, start_node=None, parent_path=""):
        """Recursively discover all nodes starting from a node"""
        if start_node is None:
            # Start from Objects folder
            start_node = self.client.nodes.objects

        try:
            # Get node info
            node_id = start_node.nodeid.to_string()
            browse_name = await start_node.read_browse_name()
            display_name = await start_node.read_display_name()
            node_class = await start_node.read_node_class()

            current_path = f"{parent_path}/{browse_name.Name}" if parent_path else browse_name.Name

            # logger.info(f"Discovered: {current_path} ({node_class})")  # Too verbose - commented out
            logger.debug(f"Discovered: {current_path} ({node_class})")

            # Track statistics
            self.discovery_stats['total_nodes'] += 1
            node_class_name = node_class.name
            self.discovery_stats['by_node_class'][node_class_name] = \
                self.discovery_stats['by_node_class'].get(node_class_name, 0) + 1

            node_info = {
                'node_id': node_id,
                'browse_name': browse_name.Name,
                'display_name': display_name.Text,
                'node_class': node_class.name,
                'parent_path': parent_path
            }

            # If it's a variable, get additional info
            if node_class == ua.NodeClass.Variable:
                try:
                    value = await start_node.read_value()
                    data_type_node = await start_node.read_data_type()
                    value_rank = await start_node.read_value_rank()

                    variant_type = None
                    is_array = False

                    # Check for arrays/lists
                    if isinstance(value, (list, tuple)):
                        is_array = True
                        # Detect array element type
                        if len(value) > 0:
                            elem = value[0]
                            if isinstance(elem, bool):
                                variant_type = 'Boolean'
                            elif isinstance(elem, int):
                                variant_type = 'Int32'
                            elif isinstance(elem, float):
                                variant_type = 'Float'
                            elif isinstance(elem, str):
                                variant_type = 'String'
                            else:
                                variant_type = 'String'  # Serialize complex array elements
                        else:
                            variant_type = 'Float'
                        logger.debug(f"Array variable: {current_path} ({variant_type}[])")

                    # Check for datetime
                    elif hasattr(value, 'year') and hasattr(value, 'month'):
                        variant_type = 'DateTime'
                        logger.debug(f"DateTime variable: {current_path}")

                    # Check for complex structures (serialize as string)
                    elif hasattr(value, '__dict__') and not isinstance(value, (int, float, str, bool)):
                        variant_type = 'String'  # Will be serialized
                        logger.debug(f"Complex structure variable: {current_path}")

                    # Simple types
                    elif isinstance(value, bool):
                        variant_type = 'Boolean'
                    elif isinstance(value, int):
                        variant_type = 'Int32'
                    elif isinstance(value, float):
                        variant_type = 'Float'
                    elif isinstance(value, str):
                        variant_type = 'String'
                    elif value is None:
                        variant_type = 'String'
                        value = ""
                    else:
                        # Unknown type - serialize as string
                        variant_type = 'String'
                        logger.debug(f"Unknown type variable: {current_path} (type: {type(value)}), will serialize")

                    node_info['data_type'] = variant_type
                    node_info['initial_value'] = value
                    node_info['is_array'] = is_array
                    node_info['value_rank'] = value_rank
                    node_info['writable'] = False  # Make shadow read-only for safety

                    # Track variable nodes for subscription
                    self.variable_nodes.append(start_node)
                    self.discovery_stats['variables_successfully_read'] += 1

                except Exception as e:
                    logger.debug(f"Could not read variable details for {current_path}: {e}")
                    # Still add it but mark it
                    node_info['read_error'] = True
                    self.discovery_stats['variables_with_read_errors'].append(f"{current_path} ({e})")

            self.discovered_nodes[node_id] = node_info

            # Browse children
            try:
                children = await start_node.get_children()
                for child in children:
                    await self.discover_nodes(child, current_path)
            except Exception as e:
                logger.debug(f"No children or error browsing {current_path}: {e}")

        except Exception as e:
            logger.error(f"Error discovering node: {e}")
            self.discovery_stats['discovery_errors'].append(f"{parent_path} ({e})")

    def _log_discovery_statistics(self):
        """Log detailed statistics about node discovery and write to file"""
        stats_lines = []

        # Build statistics text
        stats_lines.append("=" * 60)
        stats_lines.append("DISCOVERY STATISTICS:")
        stats_lines.append("=" * 60)
        stats_lines.append(f"Timestamp: {datetime.utcnow().isoformat()}")
        stats_lines.append(f"Server: {self.config['opcua_server_url']}")
        stats_lines.append(f"Total nodes discovered: {self.discovery_stats['total_nodes']}")
        stats_lines.append("")

        # Node class breakdown
        stats_lines.append("Nodes by Class:")
        for node_class, count in sorted(self.discovery_stats['by_node_class'].items(),
                                       key=lambda x: x[1], reverse=True):
            stats_lines.append(f"  {node_class}: {count} nodes")

        # Variable statistics
        total_variables = self.discovery_stats['by_node_class'].get('Variable', 0)
        successful_reads = self.discovery_stats['variables_successfully_read']
        read_errors = len(self.discovery_stats['variables_with_read_errors'])

        stats_lines.append("")
        stats_lines.append("Variable Details:")
        stats_lines.append(f"  Total variables: {total_variables}")
        stats_lines.append(f"  Successfully read: {successful_reads}")
        stats_lines.append(f"  Read errors: {read_errors}")

        if self.discovery_stats['variables_with_read_errors']:
            stats_lines.append("")
            stats_lines.append(f"Variables with Read Errors ({read_errors} total):")
            for error in self.discovery_stats['variables_with_read_errors']:
                stats_lines.append(f"  - {error}")

        # Discovery errors
        if self.discovery_stats['discovery_errors']:
            error_count = len(self.discovery_stats['discovery_errors'])
            stats_lines.append("")
            stats_lines.append(f"Discovery Errors ({error_count} total):")
            for error in self.discovery_stats['discovery_errors']:
                stats_lines.append(f"  - {error}")

        stats_lines.append("=" * 60)

        # Write to file
        stats_file = "discovery_statistics.txt"
        try:
            with open(stats_file, 'w') as f:
                f.write('\n'.join(stats_lines))
            logger.info(f"Discovery statistics written to: {stats_file}")
        except Exception as e:
            logger.error(f"Failed to write statistics file: {e}")

        # Also log to console (first 50 lines)
        logger.info("=" * 60)
        logger.info("DISCOVERY STATISTICS:")
        logger.info("=" * 60)
        for line in stats_lines[3:]:  # Skip header lines
            logger.info(line)
            if stats_lines.index(line) > 50:
                logger.info("... (see discovery_statistics.txt for full details)")
                break

    def _send_node_in_chunks(self, node_info, message_type='structure'):
        """Send a large node split across multiple UDP packets

        Args:
            node_info: Node information dictionary
            message_type: 'structure' or 'structure_add'

        Returns:
            True if successful, False otherwise
        """
        MAX_CHUNK_SIZE = 50000  # Leave room for message envelope

        # Serialize just the node data
        node_json = json.dumps(node_info, default=str)
        node_bytes = node_json.encode('utf-8')

        if len(node_bytes) > 1000000:  # 1MB limit for sanity
            logger.error(f"Node exceeds 1MB limit ({len(node_bytes)} bytes) - cannot chunk")
            return False

        # Split into chunks
        chunks = []
        for i in range(0, len(node_bytes), MAX_CHUNK_SIZE):
            chunks.append(node_bytes[i:i+MAX_CHUNK_SIZE])

        node_id = node_info.get('node_id', 'unknown')
        total_chunks = len(chunks)

        logger.info(f"Splitting node {node_id} into {total_chunks} chunks ({len(node_bytes)} bytes total)")

        # Send each chunk
        for chunk_index, chunk_data in enumerate(chunks):
            chunk_message = {
                'type': 'node_chunk',
                'message_type': message_type,  # Original message type this belongs to
                'node_id': node_id,
                'chunk_index': chunk_index,
                'total_chunks': total_chunks,
                'chunk_data': chunk_data.decode('utf-8')  # Keep as string for JSON
            }

            try:
                self._send_udp(chunk_message)
                logger.debug(f"Sent chunk {chunk_index + 1}/{total_chunks} for node {node_id}")
            except Exception as e:
                logger.error(f"Failed to send chunk {chunk_index} for node {node_id}: {e}")
                return False

        return True

    def _prepare_node_for_sending(self, node_info, aggressive=False):
        """Prepare node info for sending by truncating large initial values

        Args:
            node_info: Node information dictionary
            aggressive: If True, completely remove initial_value for maximum size reduction
        """
        node_copy = node_info.copy()

        if aggressive:
            # Aggressive mode: completely remove initial_value
            if 'initial_value' in node_copy:
                del node_copy['initial_value']
                node_copy['initial_value_stripped'] = True
        else:
            # Normal mode: truncate large initial values (arrays) to reduce payload size
            if 'initial_value' in node_copy and isinstance(node_copy['initial_value'], (list, tuple)):
                if len(node_copy['initial_value']) > 10:
                    # Keep only first 10 elements and add a marker
                    node_copy['initial_value'] = list(node_copy['initial_value'][:10])
                    node_copy['initial_value_truncated'] = True

        return node_copy

    def send_node_structure(self):
        """Send complete node structure to receiver with dynamic payload sizing"""
        total_nodes = len(self.discovered_nodes)
        logger.info(f"Sending structure of {total_nodes} nodes...")

        # Maximum safe UDP payload size (leave some headroom)
        MAX_UDP_SIZE = 60000

        # Prepare nodes with truncated large values
        nodes_list = [self._prepare_node_for_sending(node) for node in self.discovered_nodes.values()]

        batch_num = 0
        i = 0

        while i < len(nodes_list):
            # Start with adaptive batch size
            batch_size = min(10, len(nodes_list) - i)

            while batch_size > 0:
                batch = nodes_list[i:i+batch_size]

                message = {
                    'type': 'structure',
                    'batch': batch_num,
                    'total_batches': -1,  # Will be updated in completion message
                    'nodes': batch
                }

                payload = json.dumps(message, default=str).encode('utf-8')

                # Check if payload fits in UDP packet
                if len(payload) <= MAX_UDP_SIZE:
                    # Send it
                    sent_bytes = self._send_udp(message)
                    logger.debug(f"Sent batch {batch_num + 1} with {batch_size} nodes ({sent_bytes} bytes)")
                    batch_num += 1
                    i += batch_size
                    break
                else:
                    # Payload too large, reduce batch size and retry
                    if batch_size == 1:
                        # Single node is too large, try aggressive stripping
                        logger.warning(f"Single node too large ({len(payload)} bytes), stripping initial_value...")
                        aggressive_node = self._prepare_node_for_sending(
                            list(self.discovered_nodes.values())[i], aggressive=True
                        )
                        aggressive_batch = [aggressive_node]
                        message['nodes'] = aggressive_batch
                        payload = json.dumps(message, default=str).encode('utf-8')

                        if len(payload) <= MAX_UDP_SIZE:
                            sent_bytes = self._send_udp(message)
                            logger.info(f"Sent large node at index {i} without initial_value ({sent_bytes} bytes)")
                            batch_num += 1
                            i += 1
                            break
                        else:
                            # Even metadata is too large, split into chunks
                            logger.warning(f"Node metadata too large ({len(payload)} bytes), splitting into chunks...")
                            if self._send_node_in_chunks(aggressive_node, 'structure'):
                                logger.info(f"Sent chunked node at index {i}")
                                batch_num += 1
                                i += 1
                                break
                            else:
                                logger.error(f"Failed to send chunked node at index {i} - skipping")
                                i += 1
                                break
                    logger.debug(f"Batch of {batch_size} nodes too large ({len(payload)} bytes), reducing...")
                    batch_size = batch_size // 2
                    if batch_size == 0:
                        batch_size = 1  # Ensure we try with 1 before giving up

        # Send completion message
        completion_msg = {
            'type': 'structure_complete',
            'total_nodes': len(self.discovered_nodes),
            'variable_nodes': len(self.variable_nodes)
        }
        self._send_udp(completion_msg)

        logger.info(f"Structure sent: {len(self.discovered_nodes)} nodes ({len(self.variable_nodes)} variables) in {batch_num} packets")

    async def subscribe_to_variables(self):
        """Subscribe to all discovered variable nodes"""
        if not self.variable_nodes:
            logger.warning("No variable nodes to subscribe to")
            return

        total_vars = len(self.variable_nodes)
        logger.info(f"Subscribing to {total_vars} variable nodes...")

        handler = DataChangeHandler(self.udp_socket, self.udp_address, self.discovered_nodes, self)
        self.subscription = await self.client.create_subscription(
            period=self.config.get('subscription_interval', 100),
            handler=handler
        )

        # Subscribe in batches to avoid overwhelming the server
        batch_size = 100
        subscribed = 0
        for i in range(0, len(self.variable_nodes), batch_size):
            batch = self.variable_nodes[i:i+batch_size]
            try:
                await self.subscription.subscribe_data_change(batch)
                subscribed += len(batch)
                logger.debug(f"Subscribed to batch {i//batch_size + 1}/{(len(self.variable_nodes) + batch_size - 1)//batch_size}")
            except Exception as e:
                logger.error(f"Error subscribing to batch: {e}")

        logger.info(f"Subscribed to {subscribed}/{total_vars} variables")

    async def check_structure_changes(self):
        """Check if server structure has changed and send updates"""
        logger.debug("Checking for structure changes...")

        # Save current structure
        old_nodes = set(self.discovered_nodes.keys())
        old_variable_nodes = set(str(node.nodeid) for node in self.variable_nodes)

        # Re-discover (reset stats for fresh discovery)
        self.discovered_nodes = {}
        self.variable_nodes = []
        self.discovery_stats = {
            'total_nodes': 0,
            'by_node_class': {},
            'variables_with_read_errors': [],
            'variables_successfully_read': 0,
            'discovery_errors': []
        }
        await self.discover_nodes()

        # Find differences
        new_nodes = set(self.discovered_nodes.keys())
        new_variable_nodes = set(str(node.nodeid) for node in self.variable_nodes)

        added_nodes = new_nodes - old_nodes
        removed_nodes = old_nodes - new_nodes

        if added_nodes or removed_nodes:
            logger.info(f"Structure changed: {len(added_nodes)} added, {len(removed_nodes)} removed")

            # Send removed nodes notification
            if removed_nodes:
                removal_msg = {
                    'type': 'structure_remove',
                    'node_ids': list(removed_nodes)
                }
                self._send_udp(removal_msg)

            # Send added nodes with dynamic payload sizing
            if added_nodes:
                # Maximum safe UDP payload size
                MAX_UDP_SIZE = 60000

                # Prepare nodes with truncated large values
                added_node_info = [self._prepare_node_for_sending(self.discovered_nodes[nid]) for nid in added_nodes]

                batch_num = 0
                i = 0

                while i < len(added_node_info):
                    # Start with adaptive batch size
                    batch_size = min(10, len(added_node_info) - i)

                    while batch_size > 0:
                        batch = added_node_info[i:i+batch_size]

                        message = {
                            'type': 'structure_add',
                            'batch': batch_num,
                            'total_batches': -1,  # Will be updated in completion message
                            'nodes': batch
                        }

                        payload = json.dumps(message, default=str).encode('utf-8')

                        # Check if payload fits in UDP packet
                        if len(payload) <= MAX_UDP_SIZE:
                            # Send it
                            sent_bytes = self._send_udp(message)
                            logger.debug(f"Sent incremental batch {batch_num + 1} with {batch_size} nodes ({sent_bytes} bytes)")
                            batch_num += 1
                            i += batch_size
                            break
                        else:
                            # Payload too large, reduce batch size and retry
                            if batch_size == 1:
                                # Single node is too large, try aggressive stripping
                                logger.warning(f"Single node too large ({len(payload)} bytes), stripping initial_value...")
                                aggressive_node = self._prepare_node_for_sending(
                                    added_node_info[i], aggressive=True
                                )
                                aggressive_batch = [aggressive_node]
                                message['nodes'] = aggressive_batch
                                payload = json.dumps(message, default=str).encode('utf-8')

                                if len(payload) <= MAX_UDP_SIZE:
                                    sent_bytes = self._send_udp(message)
                                    logger.info(f"Sent large node at index {i} without initial_value ({sent_bytes} bytes)")
                                    batch_num += 1
                                    i += 1
                                    break
                                else:
                                    # Even metadata is too large, split into chunks
                                    logger.warning(f"Node metadata too large ({len(payload)} bytes), splitting into chunks...")
                                    if self._send_node_in_chunks(aggressive_node, 'structure_add'):
                                        logger.info(f"Sent chunked node at index {i}")
                                        batch_num += 1
                                        i += 1
                                        break
                                    else:
                                        logger.error(f"Failed to send chunked node at index {i} - skipping")
                                        i += 1
                                        break
                            logger.debug(f"Batch of {batch_size} nodes too large ({len(payload)} bytes), reducing...")
                            batch_size = batch_size // 2
                            if batch_size == 0:
                                batch_size = 1  # Ensure we try with 1 before giving up

                # Send completion
                completion_msg = {
                    'type': 'structure_add_complete',
                    'total_nodes': len(added_nodes)
                }
                self._send_udp(completion_msg)

            # Update subscriptions for new variables
            added_variables = new_variable_nodes - old_variable_nodes
            if added_variables:
                logger.info(f"Subscribing to {len(added_variables)} new variables...")
                new_vars = [node for node in self.variable_nodes if str(node.nodeid) in added_variables]

                if self.subscription and new_vars:
                    try:
                        await self.subscription.subscribe_data_change(new_vars)
                        logger.info(f"Successfully subscribed to {len(new_vars)} new variables")
                    except Exception as e:
                        logger.error(f"Error subscribing to new variables: {e}")
        else:
            logger.debug("No structure changes detected")

    async def monitor_structure_changes(self, interval=30):
        """Periodically monitor for structure changes"""
        while True:
            await asyncio.sleep(interval)
            try:
                await self.check_structure_changes()
            except Exception as e:
                logger.error(f"Error checking structure changes: {e}")

    async def run(self):
        """Main run loop"""
        try:
            await self.connect()
            await self.discover_nodes()

            # Log discovery statistics
            self._log_discovery_statistics()

            self.send_node_structure()
            await asyncio.sleep(1)  # Give receiver time to process
            await self.subscribe_to_variables()

            # Get monitoring interval from config (default 30 seconds)
            monitor_interval = self.config.get('structure_check_interval', 30)

            logger.info(f"Auto-discovery sender running. Structure monitoring every {monitor_interval}s. Press Ctrl+C to stop.")

            # Start structure monitoring in background
            monitor_task = asyncio.create_task(self.monitor_structure_changes(monitor_interval))

            while True:
                await asyncio.sleep(1)
                # Log periodic summary every iteration (function checks internally for 30s interval)
                self.log_periodic_summary()

        except KeyboardInterrupt:
            logger.info("Shutting down sender...")
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
        finally:
            if 'monitor_task' in locals():
                monitor_task.cancel()
            if self.client:
                await self.client.disconnect()
            if self.udp_socket:
                self.udp_socket.close()
            logger.info("Sender stopped")


class DataChangeHandler:
    """Handler for OPC UA data change notifications"""

    def __init__(self, udp_socket, udp_address, node_info_dict, sender_instance):
        self.udp_socket = udp_socket
        self.udp_address = udp_address
        self.node_info_dict = node_info_dict
        self.sender = sender_instance  # Reference to sender for _send_udp method

    def datachange_notification(self, node, val, data):
        """Called when a subscribed node value changes"""
        try:
            node_id = str(node)
            node_info = self.node_info_dict.get(node_id, {})

            payload = {
                'type': 'data_change',
                'node_id': node_id,
                'value': val,
                'timestamp': datetime.utcnow().isoformat(),
                'source_timestamp': data.monitored_item.Value.SourceTimestamp.isoformat() if data.monitored_item.Value.SourceTimestamp else None,
            }

            self.sender._send_udp(payload)

            # Track statistics
            self.sender.runtime_stats['data_changes_sent'] += 1

            logger.debug(f"Sent: {node_info.get('browse_name', node_id)} = {val}")

        except Exception as e:
            logger.error(f"Error in datachange_notification: {e}")


async def async_main():
    """Async main function"""
    import sys

    # Handle --version flag
    if len(sys.argv) > 1 and sys.argv[1] in ('--version', '-v'):
        from opcua_data_diode import __version__
        print(f"opcua-sender version {__version__}")
        return

    config_file = sys.argv[1] if len(sys.argv) > 1 else 'sender_config.json'

    with open(config_file, 'r') as f:
        config = json.load(f)

    # Important warning
    logger.warning("=" * 70)
    logger.warning("⚠️  IMPORTANT: Make sure the RECEIVER and real OPC UA Server are running FIRST!")
    logger.warning("   The sender requires both the receiver and the real OPC UA server to be active before starting.")
    logger.warning("=" * 70)

    sender = AutoDiscoverySender(config)
    await sender.run()


def main():
    """Entry point for console script"""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
