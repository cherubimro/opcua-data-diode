#!/usr/bin/env python3
"""
OPC UA Auto-Discovery Receiver - Dynamically creates shadow server from UDP stream
"""
import asyncio
import json
import socket
import logging
import zlib
import base64
from datetime import datetime
from asyncua import Server
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


class AutoShadowServer:
    """Shadow OPC UA server that dynamically mirrors discovered nodes"""

    def __init__(self, config):
        # Support both old format {'receiver': {...}} and new format with direct config
        if 'receiver' in config:
            self.config = config['receiver']
        else:
            self.config = config

        self.server = None
        self.udp_socket = None
        self.running = False

        # Node tracking
        self.node_structure = {}  # Original node_id -> node info
        self.shadow_nodes = {}  # Original node_id -> shadow node object
        self.pending_children = {}  # Track parent-child relationships to build later
        self.namespace_idx = None
        self.structure_complete = False

        # Root objects for building hierarchy
        self.shadow_root = None

        # Chunk reassembly buffer
        self.chunk_buffer = {}  # node_id -> {chunks: {index: data}, total_chunks: N, message_type: 'structure'}

        # Encryption settings
        self.encryption_enabled = self.config.get('encryption', {}).get('enabled', False)
        self.encryption_algorithm = self.config.get('encryption', {}).get('algorithm', 'aes-256-gcm').lower()
        self.ciphers = {}  # Dictionary to hold multiple cipher instances

        if self.encryption_enabled:
            encryption_key = self.config.get('encryption', {}).get('key', '')
            if not encryption_key:
                logger.error("Encryption enabled but no key provided in config. Disabling encryption.")
                self.encryption_enabled = False
            else:
                try:
                    # Decode the base64 key
                    key_bytes = base64.b64decode(encryption_key)

                    # Initialize all ciphers for decryption (receiver must support all)
                    # This allows gradual migration between algorithms

                    # AES-128-GCM (algorithm_id: 0x01)
                    if len(key_bytes) >= 16:
                        self.ciphers[0x01] = AESGCM(key_bytes[:16])

                    # AES-256-GCM (algorithm_id: 0x02) and ChaCha20-Poly1305 (0x03)
                    if len(key_bytes) >= 32:
                        self.ciphers[0x02] = AESGCM(key_bytes[:32])
                        self.ciphers[0x03] = ChaCha20Poly1305(key_bytes[:32])

                    # Fernet (algorithm_id: 0x00) - legacy
                    try:
                        self.ciphers[0x00] = Fernet(encryption_key.encode())
                    except:
                        pass  # Fernet key format may not be compatible with raw bytes

                    # Log configured algorithm
                    if self.encryption_algorithm == 'aes-128-gcm':
                        logger.info("Encryption enabled: AES-128-GCM")
                    elif self.encryption_algorithm == 'aes-256-gcm':
                        logger.info("Encryption enabled: AES-256-GCM")
                    elif self.encryption_algorithm == 'chacha20-poly1305':
                        logger.info("Encryption enabled: ChaCha20-Poly1305")
                    elif self.encryption_algorithm == 'fernet':
                        logger.info("Encryption enabled: Fernet (AES-128-CBC) - LEGACY")
                    else:
                        logger.warning(f"Unknown algorithm {self.encryption_algorithm}, supporting all available")

                except Exception as e:
                    logger.error(f"Invalid encryption configuration: {e}. Disabling encryption.")
                    self.encryption_enabled = False

    async def init_server(self):
        """Initialize the shadow OPC UA server"""
        self.server = Server()
        await self.server.init()

        self.server.set_endpoint(f"opc.tcp://0.0.0.0:{self.config['shadow_server_port']}/shadow/")
        self.server.set_server_name(self.config['shadow_server_name'])

        # Register custom namespace
        uri = "http://opcua.shadow.server"
        self.namespace_idx = await self.server.register_namespace(uri)

        # Get the Objects node where we'll build the shadow structure
        self.shadow_root = self.server.nodes.objects

        logger.info("Shadow server initialized, waiting for structure...")

    async def start_server(self):
        """Start the shadow OPC UA server"""
        await self.server.start()
        logger.info(f"Shadow OPC UA server started on port {self.config['shadow_server_port']}")

    async def stop_server(self):
        """Stop the shadow OPC UA server"""
        await self.server.stop()
        logger.info("Shadow OPC UA server stopped")

    def setup_udp_listener(self):
        """Setup UDP socket for receiving data"""
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_socket.bind((self.config['udp_host'], self.config['udp_port']))
        self.udp_socket.setblocking(False)
        logger.info(f"UDP listener bound to {self.config['udp_host']}:{self.config['udp_port']}")

    def _decrypt_payload(self, data):
        """Decrypt payload if it was encrypted

        Protocol: [encryption_flag:1byte][algorithm_id:1byte if encrypted][encrypted/plain data]
        Returns decrypted data (still includes compression headers)
        """
        try:
            # Check encryption flag (first byte)
            if data[0:1] == b'\x00':
                # Not encrypted
                return data[1:]
            elif data[0:1] == b'\x01':
                # Encrypted - get algorithm ID (second byte)
                if len(data) < 2:
                    logger.error("Encrypted packet too short")
                    return None

                algorithm_id = data[1]

                if not self.encryption_enabled or algorithm_id not in self.ciphers:
                    logger.error(f"Received encrypted data with algorithm ID {algorithm_id} but not configured")
                    return None

                cipher = self.ciphers[algorithm_id]
                encrypted_data = data[2:]

                try:
                    if algorithm_id == 0x00:
                        # Fernet - handles everything internally
                        return cipher.decrypt(encrypted_data)
                    else:
                        # AEAD ciphers (GCM, ChaCha20-Poly1305)
                        # Extract nonce (first 12 bytes) and ciphertext+tag (remaining)
                        if len(encrypted_data) < 12:
                            logger.error("Encrypted data too short for nonce")
                            return None

                        nonce = encrypted_data[:12]
                        ciphertext = encrypted_data[12:]

                        # Decrypt and verify (raises exception if auth tag invalid)
                        return cipher.decrypt(nonce, ciphertext, None)

                except Exception as e:
                    logger.error(f"Decryption failed for algorithm {algorithm_id}: {e}")
                    return None
            else:
                logger.warning(f"Unknown encryption flag: {data[0]}")
                return data[1:]  # Try to use as-is
        except Exception as e:
            logger.error(f"Decryption processing failed: {e}")
            return None

    def _decompress_payload(self, data):
        """Decompress payload if it was compressed"""
        try:
            # Check compression flag (first byte)
            if data[0:1] == b'\x00':
                # Not compressed
                return data[1:]
            elif data[0:1] == b'\x01':
                # Compressed - check method (second byte)
                method_byte = data[1:2]
                compressed_data = data[2:]

                if method_byte == b'\x01':
                    # LZ4 compression
                    if HAS_LZ4:
                        return lz4.frame.decompress(compressed_data)
                    else:
                        logger.error("Received LZ4 compressed data but lz4 not installed")
                        return None
                else:
                    # zlib compression (b'\x00' or default)
                    return zlib.decompress(compressed_data)
            else:
                logger.warning(f"Unknown compression flag: {data[0]}")
                return data  # Try to use as-is
        except Exception as e:
            logger.error(f"Decompression failed: {e}")
            return None

    async def udp_listener_loop(self):
        """Async loop to receive and process UDP packets"""
        self.running = True
        logger.info("UDP listener started")

        while self.running:
            try:
                data, addr = await asyncio.get_event_loop().sock_recvfrom(self.udp_socket, 65536)

                # Decrypt if needed (outer layer)
                decrypted_data = self._decrypt_payload(data)
                if decrypted_data is None:
                    continue  # Skip this packet if decryption failed

                # Decompress if needed (inner layer)
                decompressed_data = self._decompress_payload(decrypted_data)
                if decompressed_data is None:
                    continue  # Skip this packet if decompression failed

                payload = json.loads(decompressed_data.decode('utf-8'))

                msg_type = payload.get('type')

                if msg_type == 'structure':
                    await self.process_structure_batch(payload)
                elif msg_type == 'structure_complete':
                    await self.finalize_structure(payload)
                elif msg_type == 'structure_add':
                    await self.process_structure_add(payload)
                elif msg_type == 'structure_add_complete':
                    await self.finalize_structure_add(payload)
                elif msg_type == 'structure_remove':
                    await self.process_structure_remove(payload)
                elif msg_type == 'data_change':
                    await self.update_shadow_node(payload)
                elif msg_type == 'node_chunk':
                    await self.process_node_chunk(payload)

            except BlockingIOError:
                await asyncio.sleep(0.01)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON: {e}")
            except Exception as e:
                logger.error(f"Error in UDP listener: {e}", exc_info=True)

    async def process_node_chunk(self, payload):
        """Process a chunk of a large node and reassemble when complete"""
        node_id = payload.get('node_id')
        chunk_index = payload.get('chunk_index')
        total_chunks = payload.get('total_chunks')
        chunk_data = payload.get('chunk_data')
        message_type = payload.get('message_type', 'structure')

        if not node_id:
            logger.error("Received chunk without node_id")
            return

        # Initialize buffer for this node if needed
        if node_id not in self.chunk_buffer:
            self.chunk_buffer[node_id] = {
                'chunks': {},
                'total_chunks': total_chunks,
                'message_type': message_type
            }

        # Store this chunk
        self.chunk_buffer[node_id]['chunks'][chunk_index] = chunk_data
        logger.debug(f"Received chunk {chunk_index + 1}/{total_chunks} for node {node_id}")

        # Check if we have all chunks
        if len(self.chunk_buffer[node_id]['chunks']) == total_chunks:
            logger.info(f"Reassembling {total_chunks} chunks for node {node_id}")

            # Reassemble in order
            full_data = ''
            for i in range(total_chunks):
                if i not in self.chunk_buffer[node_id]['chunks']:
                    logger.error(f"Missing chunk {i} for node {node_id}")
                    del self.chunk_buffer[node_id]
                    return
                full_data += self.chunk_buffer[node_id]['chunks'][i]

            # Parse the reassembled node
            try:
                node_info = json.loads(full_data)
                logger.info(f"Successfully reassembled node {node_id} ({len(full_data)} bytes)")

                # Add to node structure based on message type
                self.node_structure[node_id] = node_info

                # Clean up buffer
                del self.chunk_buffer[node_id]

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse reassembled node {node_id}: {e}")
                del self.chunk_buffer[node_id]

    async def process_structure_batch(self, payload):
        """Process a batch of node structure information"""
        batch_num = payload.get('batch', 0)
        nodes = payload.get('nodes', [])

        logger.info(f"Processing structure batch {batch_num + 1}/{payload.get('total_batches', '?')} ({len(nodes)} nodes)")

        for node_info in nodes:
            node_id = node_info['node_id']
            self.node_structure[node_id] = node_info

    async def finalize_structure(self, payload):
        """Build the shadow server structure after all batches received"""
        logger.info(f"Structure complete. Received {len(self.node_structure)} nodes")
        logger.info("Building shadow server structure...")

        # Build nodes in order: Objects first, then Variables
        # Sort by parent_path depth to ensure parents are created before children
        sorted_nodes = sorted(
            self.node_structure.items(),
            key=lambda x: (x[1]['parent_path'].count('/'), x[1]['node_class'] == 'Variable')
        )

        created_count = 0
        skipped_count = 0
        skip_reasons = {
            'parent_not_found': [],
            'read_error': [],
            'unsupported_node_class': [],
            'variable_creation_failed': [],
            'general_error': []
        }

        for node_id, node_info in sorted_nodes:
            try:
                # Skip root Objects node as it already exists
                if node_info['browse_name'] == 'Objects' and not node_info['parent_path']:
                    self.shadow_nodes[node_id] = self.shadow_root
                    continue

                parent_node = self._find_parent_node(node_info)
                if parent_node is None:
                    skipped_count += 1
                    skip_reasons['parent_not_found'].append(node_info['browse_name'])
                    logger.debug(f"Skipping {node_info['browse_name']} - parent not found")
                    continue

                if node_info['node_class'] == 'Object':
                    shadow_node = await parent_node.add_object(
                        self.namespace_idx,
                        node_info['browse_name']
                    )
                    self.shadow_nodes[node_id] = shadow_node
                    created_count += 1
                    logger.debug(f"Created object: {node_info['browse_name']}")

                elif node_info['node_class'] == 'Method':
                    # Create method as non-executable placeholder
                    try:
                        shadow_node = await parent_node.add_method(
                            self.namespace_idx,
                            node_info['browse_name'],
                            func=None  # No implementation - just structure
                        )
                        self.shadow_nodes[node_id] = shadow_node
                        created_count += 1
                        logger.debug(f"Created method placeholder: {node_info['browse_name']}")
                    except Exception as e:
                        # If add_method fails, create as object instead (fallback)
                        logger.debug(f"Creating method as object: {node_info['browse_name']}")
                        shadow_node = await parent_node.add_object(
                            self.namespace_idx,
                            node_info['browse_name']
                        )
                        self.shadow_nodes[node_id] = shadow_node
                        created_count += 1

                elif node_info['node_class'] == 'Variable':
                    # Skip if there was a read error
                    if node_info.get('read_error'):
                        skipped_count += 1
                        skip_reasons['read_error'].append(node_info['browse_name'])
                        logger.debug(f"Skipping variable with read error: {node_info['browse_name']}")
                        continue

                    # Get initial value and type
                    data_type = node_info.get('data_type', 'Float')
                    is_array = node_info.get('is_array', False)
                    is_truncated = node_info.get('initial_value_truncated', False)
                    is_stripped = node_info.get('initial_value_stripped', False)

                    # Handle stripped initial values (too large to send)
                    if is_stripped:
                        logger.info(f"Using default value for stripped variable: {node_info['browse_name']}")
                        if is_array:
                            initial_value = []
                        elif data_type in ('Float', 'Double'):
                            initial_value = 0.0
                        elif data_type in ('Int32', 'Int64'):
                            initial_value = 0
                        elif data_type == 'Boolean':
                            initial_value = False
                        else:
                            initial_value = ""
                    else:
                        initial_value = node_info.get('initial_value', 0)

                        # Prepare initial value based on type
                        if data_type == 'DateTime':
                            # Convert datetime to string for JSON, will be handled specially
                            if initial_value and hasattr(initial_value, 'isoformat'):
                                initial_value = initial_value.isoformat()
                            else:
                                initial_value = str(initial_value)
                        elif is_array:
                            # Handle arrays - use empty array if truncated (will be updated via subscription)
                            if is_truncated:
                                initial_value = []
                                logger.debug(f"Using empty array for truncated variable: {node_info['browse_name']}")
                            elif isinstance(initial_value, (list, tuple)):
                                initial_value = [self._serialize_value(v) for v in initial_value]
                            else:
                                initial_value = []
                        else:
                            # Serialize complex objects to strings
                            initial_value = self._serialize_value(initial_value)

                    variant_type = self._get_ua_type(data_type)

                    # Create the variable
                    try:
                        shadow_node = await parent_node.add_variable(
                            self.namespace_idx,
                            node_info['browse_name'],
                            initial_value,
                            varianttype=variant_type
                        )
                        await shadow_node.set_writable()

                        self.shadow_nodes[node_id] = shadow_node
                        created_count += 1
                        logger.debug(f"Created variable: {node_info['browse_name']} (type: {data_type}, array: {is_array})")
                    except Exception as e:
                        logger.debug(f"Failed to create variable {node_info['browse_name']}: {e}")
                        skipped_count += 1
                        skip_reasons['variable_creation_failed'].append(f"{node_info['browse_name']} ({e})")

                elif node_info['node_class'] in ['DataType', 'ReferenceType', 'View', 'ObjectType', 'VariableType']:
                    # Create these node types as Objects for structure preservation
                    try:
                        shadow_node = await parent_node.add_object(
                            self.namespace_idx,
                            node_info['browse_name']
                        )
                        self.shadow_nodes[node_id] = shadow_node
                        created_count += 1
                        logger.debug(f"Created {node_info['node_class']} as object: {node_info['browse_name']}")
                    except Exception as e:
                        logger.debug(f"Failed to create {node_info['node_class']}: {node_info['browse_name']} ({e})")
                        skipped_count += 1
                        skip_reasons['general_error'].append(f"{node_info['browse_name']} ({e})")

                else:
                    # Truly unsupported node class
                    skipped_count += 1
                    skip_reasons['unsupported_node_class'].append(f"{node_info['browse_name']} ({node_info['node_class']})")
                    logger.debug(f"Skipping unsupported node class: {node_info['browse_name']} ({node_info['node_class']})")

            except Exception as e:
                logger.debug(f"Could not create {node_info['browse_name']}: {e}")
                skipped_count += 1
                skip_reasons['general_error'].append(f"{node_info['browse_name']} ({e})")

        logger.info(f"Shadow structure built: {created_count} nodes created, {skipped_count} skipped")

        # Log detailed skip statistics
        self._log_skip_statistics(skip_reasons)

        self.structure_complete = True

    async def process_structure_add(self, payload):
        """Process incremental node additions"""
        batch_num = payload.get('batch', 0)
        nodes = payload.get('nodes', [])

        logger.info(f"Processing incremental add batch {batch_num + 1}/{payload.get('total_batches', '?')} ({len(nodes)} nodes)")

        for node_info in nodes:
            node_id = node_info['node_id']
            self.node_structure[node_id] = node_info

    async def finalize_structure_add(self, payload):
        """Finalize incremental node additions by creating them"""
        total_added = payload.get('total_nodes', 0)
        logger.info(f"Finalizing incremental add of {total_added} nodes...")

        # Get only the newly added nodes (those not in shadow_nodes yet)
        new_nodes = {nid: info for nid, info in self.node_structure.items() if nid not in self.shadow_nodes}

        # Sort by depth to ensure parents are created first
        sorted_nodes = sorted(
            new_nodes.items(),
            key=lambda x: (x[1]['parent_path'].count('/'), x[1]['node_class'] == 'Variable')
        )

        created_count = 0
        skipped_count = 0
        skip_reasons = {
            'parent_not_found': [],
            'read_error': [],
            'unsupported_node_class': [],
            'variable_creation_failed': [],
            'general_error': []
        }

        for node_id, node_info in sorted_nodes:
            try:
                # Skip root Objects node
                if node_info['browse_name'] == 'Objects' and not node_info['parent_path']:
                    continue

                parent_node = self._find_parent_node(node_info)
                if parent_node is None:
                    skipped_count += 1
                    skip_reasons['parent_not_found'].append(node_info['browse_name'])
                    logger.debug(f"Skipping {node_info['browse_name']} - parent not found")
                    continue

                if node_info['node_class'] == 'Object':
                    shadow_node = await parent_node.add_object(
                        self.namespace_idx,
                        node_info['browse_name']
                    )
                    self.shadow_nodes[node_id] = shadow_node
                    created_count += 1
                    logger.info(f"Added object: {node_info['browse_name']}")

                elif node_info['node_class'] == 'Method':
                    # Create method as non-executable placeholder
                    try:
                        shadow_node = await parent_node.add_method(
                            self.namespace_idx,
                            node_info['browse_name'],
                            func=None  # No implementation - just structure
                        )
                        self.shadow_nodes[node_id] = shadow_node
                        created_count += 1
                        logger.info(f"Added method placeholder: {node_info['browse_name']}")
                    except Exception as e:
                        # If add_method fails, create as object instead (fallback)
                        logger.debug(f"Creating method as object: {node_info['browse_name']}")
                        shadow_node = await parent_node.add_object(
                            self.namespace_idx,
                            node_info['browse_name']
                        )
                        self.shadow_nodes[node_id] = shadow_node
                        created_count += 1

                elif node_info['node_class'] == 'Variable':
                    if node_info.get('read_error'):
                        skipped_count += 1
                        skip_reasons['read_error'].append(node_info['browse_name'])
                        continue

                    data_type = node_info.get('data_type', 'Float')
                    is_array = node_info.get('is_array', False)
                    is_truncated = node_info.get('initial_value_truncated', False)
                    is_stripped = node_info.get('initial_value_stripped', False)

                    # Handle stripped initial values (too large to send)
                    if is_stripped:
                        logger.info(f"Using default value for stripped variable: {node_info['browse_name']}")
                        if is_array:
                            initial_value = []
                        elif data_type in ('Float', 'Double'):
                            initial_value = 0.0
                        elif data_type in ('Int32', 'Int64'):
                            initial_value = 0
                        elif data_type == 'Boolean':
                            initial_value = False
                        else:
                            initial_value = ""
                    else:
                        initial_value = node_info.get('initial_value', 0)

                        # Prepare initial value
                        if data_type == 'DateTime':
                            if initial_value and hasattr(initial_value, 'isoformat'):
                                initial_value = initial_value.isoformat()
                            else:
                                initial_value = str(initial_value)
                        elif is_array:
                            # Handle arrays - use empty array if truncated (will be updated via subscription)
                            if is_truncated:
                                initial_value = []
                                logger.debug(f"Using empty array for truncated variable: {node_info['browse_name']}")
                            elif isinstance(initial_value, (list, tuple)):
                                initial_value = [self._serialize_value(v) for v in initial_value]
                            else:
                                initial_value = []
                        else:
                            initial_value = self._serialize_value(initial_value)

                    variant_type = self._get_ua_type(data_type)

                    try:
                        shadow_node = await parent_node.add_variable(
                            self.namespace_idx,
                            node_info['browse_name'],
                            initial_value,
                            varianttype=variant_type
                        )
                        await shadow_node.set_writable()

                        self.shadow_nodes[node_id] = shadow_node
                        created_count += 1
                        logger.info(f"Added variable: {node_info['browse_name']}")
                    except Exception as e:
                        logger.debug(f"Failed to create variable {node_info['browse_name']}: {e}")
                        skipped_count += 1
                        skip_reasons['variable_creation_failed'].append(f"{node_info['browse_name']} ({e})")

                elif node_info['node_class'] in ['DataType', 'ReferenceType', 'View', 'ObjectType', 'VariableType']:
                    # Create these node types as Objects for structure preservation
                    try:
                        shadow_node = await parent_node.add_object(
                            self.namespace_idx,
                            node_info['browse_name']
                        )
                        self.shadow_nodes[node_id] = shadow_node
                        created_count += 1
                        logger.info(f"Added {node_info['node_class']} as object: {node_info['browse_name']}")
                    except Exception as e:
                        logger.debug(f"Failed to create {node_info['node_class']}: {node_info['browse_name']} ({e})")
                        skipped_count += 1
                        skip_reasons['general_error'].append(f"{node_info['browse_name']} ({e})")

                else:
                    # Truly unsupported node class
                    skipped_count += 1
                    skip_reasons['unsupported_node_class'].append(f"{node_info['browse_name']} ({node_info['node_class']})")
                    logger.debug(f"Skipping unsupported node class: {node_info['browse_name']} ({node_info['node_class']})")

            except Exception as e:
                logger.debug(f"Could not create {node_info['browse_name']}: {e}")
                skipped_count += 1
                skip_reasons['general_error'].append(f"{node_info['browse_name']} ({e})")

        logger.info(f"Incremental add complete: {created_count} nodes added, {skipped_count} skipped")
        logger.info(f"Total shadow nodes: {len(self.shadow_nodes)}")

        # Log detailed skip statistics
        self._log_skip_statistics(skip_reasons)

    async def process_structure_remove(self, payload):
        """Process node removals"""
        node_ids = payload.get('node_ids', [])
        logger.info(f"Processing removal of {len(node_ids)} nodes...")

        removed_count = 0
        for node_id in node_ids:
            if node_id in self.shadow_nodes:
                # Note: asyncua doesn't have a simple delete method, so we just remove from tracking
                # The node remains in the server but we stop updating it
                del self.shadow_nodes[node_id]
                removed_count += 1

            if node_id in self.node_structure:
                del self.node_structure[node_id]

        logger.info(f"Removed {removed_count} nodes from tracking")
        logger.info(f"Total shadow nodes: {len(self.shadow_nodes)}")

    def _log_skip_statistics(self, skip_reasons):
        """Log detailed statistics about skipped nodes and write to file"""
        stats_lines = []

        # Build statistics text
        stats_lines.append("=" * 60)
        stats_lines.append("SKIP STATISTICS:")
        stats_lines.append("=" * 60)
        stats_lines.append(f"Timestamp: {datetime.utcnow().isoformat()}")
        stats_lines.append(f"Total nodes in structure: {len(self.node_structure)}")
        stats_lines.append(f"Total nodes created: {len(self.shadow_nodes)}")
        total_skipped = sum(len(nodes) for nodes in skip_reasons.values())
        stats_lines.append(f"Total nodes skipped: {total_skipped}")
        stats_lines.append("")

        for reason, nodes in skip_reasons.items():
            if nodes:
                count = len(nodes)
                stats_lines.append(f"{reason.replace('_', ' ').title()}: {count} nodes")

                # Show all examples in file
                for example in nodes:
                    stats_lines.append(f"  - {example}")
                stats_lines.append("")

        # Summary by node class if available
        node_class_summary = {}
        for reason, nodes in skip_reasons.items():
            if reason == 'unsupported_node_class':
                for node_str in nodes:
                    # Extract node class from format "NodeName (NodeClass)"
                    if '(' in node_str:
                        node_class = node_str.split('(')[-1].rstrip(')')
                        node_class_summary[node_class] = node_class_summary.get(node_class, 0) + 1

        if node_class_summary:
            stats_lines.append("Unsupported Node Classes Summary:")
            for node_class, count in sorted(node_class_summary.items(), key=lambda x: x[1], reverse=True):
                stats_lines.append(f"  {node_class}: {count} nodes")
            stats_lines.append("")

        stats_lines.append("=" * 60)

        # Write to file
        stats_file = "skip_statistics.txt"
        try:
            with open(stats_file, 'w') as f:
                f.write('\n'.join(stats_lines))
            logger.info(f"Skip statistics written to: {stats_file}")
        except Exception as e:
            logger.error(f"Failed to write statistics file: {e}")

        # Also log to console (abbreviated)
        logger.info("=" * 60)
        logger.info("SKIP STATISTICS:")
        logger.info("=" * 60)
        logger.info(f"Total nodes created: {len(self.shadow_nodes)}")
        logger.info(f"Total nodes skipped: {total_skipped}")
        logger.info("")

        for reason, nodes in skip_reasons.items():
            if nodes:
                count = len(nodes)
                logger.info(f"{reason.replace('_', ' ').title()}: {count} nodes")
                # Show first 5 examples
                for example in nodes[:5]:
                    logger.info(f"  - {example}")
                if count > 5:
                    logger.info(f"  ... and {count - 5} more")
                logger.info("")

        if node_class_summary:
            logger.info("Unsupported Node Classes Summary:")
            for node_class, count in sorted(node_class_summary.items(), key=lambda x: x[1], reverse=True):
                logger.info(f"  {node_class}: {count} nodes")

        logger.info("=" * 60)
        logger.info(f"Full details in: {stats_file}")

    def _find_parent_node(self, node_info):
        """Find the parent shadow node for a given node"""
        parent_path = node_info['parent_path']

        if not parent_path or parent_path == 'Objects':
            return self.shadow_root

        # Try to find parent by matching path
        for orig_id, orig_info in self.node_structure.items():
            full_path = f"{orig_info['parent_path']}/{orig_info['browse_name']}" if orig_info['parent_path'] else orig_info['browse_name']
            if full_path == parent_path and orig_id in self.shadow_nodes:
                return self.shadow_nodes[orig_id]

        return None

    async def update_shadow_node(self, payload):
        """Update a shadow node with received data"""
        try:
            if not self.structure_complete:
                return  # Wait for structure to be built

            node_id = payload['node_id']

            if node_id not in self.shadow_nodes:
                # Node not in shadow
                return

            shadow_node = self.shadow_nodes[node_id]
            value = payload['value']

            # Get the expected type
            node_info = self.node_structure.get(node_id, {})
            data_type = node_info.get('data_type', 'Float')
            is_array = node_info.get('is_array', False)

            # Convert and write value
            try:
                if is_array:
                    # Handle array values
                    if isinstance(value, (list, tuple)):
                        converted_value = [self._convert_value(v, data_type) for v in value]
                    else:
                        converted_value = []
                else:
                    converted_value = self._convert_value(value, data_type)

                ua_type = self._get_ua_type(data_type)
                variant = ua.Variant(converted_value, ua_type)

                await shadow_node.write_value(variant)

                logger.debug(f"Updated: {node_info.get('browse_name', node_id)} = {converted_value if not is_array else f'[{len(converted_value)} items]'}")

            except (ValueError, TypeError) as e:
                # Type conversion failed - log as warning
                logger.debug(f"Type conversion failed for {node_info.get('browse_name', node_id)}: {e}")

        except Exception as e:
            logger.debug(f"Error updating shadow node: {e}")

    def _get_ua_type(self, type_string):
        """Convert string data type to UA variant type"""
        type_map = {
            'Float': ua.VariantType.Float,
            'Double': ua.VariantType.Double,
            'Int32': ua.VariantType.Int32,
            'Int64': ua.VariantType.Int64,
            'Boolean': ua.VariantType.Boolean,
            'String': ua.VariantType.String,
            'DateTime': ua.VariantType.String,  # Store as string for now
        }
        return type_map.get(type_string, ua.VariantType.String)

    def _convert_value(self, value, type_string):
        """Convert value to the correct Python type"""
        try:
            if type_string == 'Float' or type_string == 'Double':
                return float(value)
            elif type_string == 'Int32' or type_string == 'Int64':
                return int(value)
            elif type_string == 'Boolean':
                return bool(value)
            elif type_string == 'DateTime':
                # Keep datetime as string
                return str(value)
            elif type_string == 'String':
                return str(value)
            else:
                return str(value)
        except:
            return str(value)  # Fallback to string

    def _serialize_value(self, value):
        """Serialize a value for storage (handles complex types)"""
        if isinstance(value, (int, float, str, bool)):
            return value
        elif value is None:
            return ""
        elif hasattr(value, 'isoformat'):  # datetime
            return value.isoformat()
        elif hasattr(value, '__dict__'):  # complex object
            return str(value)
        else:
            return str(value)

    def cleanup(self):
        """Cleanup resources"""
        self.running = False
        if self.udp_socket:
            self.udp_socket.close()


async def async_main():
    """Async main receiver function"""
    import sys

    # Handle --version flag
    if len(sys.argv) > 1 and sys.argv[1] in ('--version', '-v'):
        from opcua_data_diode import __version__
        print(f"opcua-receiver version {__version__}")
        return

    config_file = sys.argv[1] if len(sys.argv) > 1 else 'receiver_config.json'

    with open(config_file, 'r') as f:
        config = json.load(f)

    shadow = AutoShadowServer(config)

    try:
        await shadow.init_server()
        await shadow.start_server()

        shadow.setup_udp_listener()
        udp_task = asyncio.create_task(shadow.udp_listener_loop())

        logger.info("Auto-discovery receiver running. Press Ctrl+C to stop.")

        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        logger.info("Shutting down receiver...")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
    finally:
        shadow.cleanup()
        if 'udp_task' in locals():
            udp_task.cancel()
        await shadow.stop_server()
        logger.info("Receiver stopped")


def main():
    """Entry point for console script"""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
