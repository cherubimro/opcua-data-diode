#!/usr/bin/env python3
"""
OPC UA Receiver GUI (ncurses) - Terminal interface for receiver_auto.py

Copyright (C) 2026 Alin-Adrian Anton <alin.anton@upt.ro>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
import curses
import json
import subprocess
import sys
import os
from curses import panel
from curses.textpad import Textbox, rectangle

class ReceiverGUINCurses:
    def __init__(self, stdscr, config_file='receiver_config.json'):
        self.stdscr = stdscr
        self.config_file = config_file
        self.config = {}
        self.process = None
        self.log_file = None
        self.current_tab = 0  # 0=Config, 1=About
        self.current_field = 0
        self.scroll_offset = 0  # For scrolling in config tab
        self.status_message = ""
        self.edit_mode = False

        # Initialize colors
        curses.start_color()
        curses.init_pair(1, curses.COLOR_RED, curses.COLOR_BLACK)      # Stopped
        curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)    # Running
        curses.init_pair(3, curses.COLOR_CYAN, curses.COLOR_BLACK)     # Headers
        curses.init_pair(4, curses.COLOR_YELLOW, curses.COLOR_BLACK)   # Highlight
        curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_BLUE)     # Selected
        curses.init_pair(6, curses.COLOR_BLUE, curses.COLOR_BLACK)     # Links

        self.load_config()

    def load_config(self):
        """Load configuration from JSON file"""
        try:
            with open(self.config_file, 'r') as f:
                self.config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.config = self.get_default_config()

    def get_default_config(self):
        """Return default configuration"""
        return {
            "udp_host": "0.0.0.0",
            "udp_port": 5555,
            "shadow_server_port": 4841,
            "shadow_server_name": "Shadow OPC UA Server",
            "encryption": {"enabled": False, "algorithm": "aes-256-gcm", "key": ""}
        }

    def save_config(self):
        """Save configuration to JSON file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
            self.status_message = "Configuration saved successfully!"
            return True
        except Exception as e:
            self.status_message = f"Error saving config: {e}"
            return False

    def is_running(self):
        """Check if receiver process is running"""
        return self.process and self.process.poll() is None

    def start_receiver(self):
        """Start the receiver process"""
        if self.is_running():
            self.status_message = "Receiver is already running!"
            return

        try:
            log_file = open('receiver_auto.log', 'w')
            self.log_file = log_file

            self.process = subprocess.Popen(
                ['opcua-receiver', self.config_file],
                stdout=log_file,
                stderr=subprocess.STDOUT
            )
            self.status_message = "Receiver started successfully"
        except Exception as e:
            self.status_message = f"Failed to start receiver: {e}"

    def stop_receiver(self):
        """Stop the receiver process"""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

            self.process = None

            if self.log_file:
                self.log_file.close()
                self.log_file = None

            self.status_message = "Receiver stopped"

    def draw_header(self):
        """Draw the header with title and tabs"""
        height, width = self.stdscr.getmaxyx()

        # Title
        title = "OPC UA Receiver - Shadow Server"
        self.stdscr.addstr(0, (width - len(title)) // 2, title,
                          curses.color_pair(3) | curses.A_BOLD)

        # Tabs
        tabs = ["[Config]", "[About]"]
        tab_x = 2
        for i, tab in enumerate(tabs):
            attr = curses.color_pair(5) | curses.A_BOLD if i == self.current_tab else curses.A_NORMAL
            self.stdscr.addstr(1, tab_x, tab, attr)
            tab_x += len(tab) + 2

        # Separator
        self.stdscr.addstr(2, 0, "─" * width)

    def draw_status_line(self):
        """Draw the status line at bottom"""
        height, width = self.stdscr.getmaxyx()

        # Status indicator
        if self.is_running():
            status_text = "● RUNNING"
            status_color = curses.color_pair(2)
        else:
            status_text = "● STOPPED"
            status_color = curses.color_pair(1)

        self.stdscr.addstr(height - 3, 2, status_text, status_color | curses.A_BOLD)

        # Status message
        if self.status_message:
            msg = self.status_message[:width-4]
            self.stdscr.addstr(height - 3, 20, msg, curses.color_pair(4))

        # Separator
        self.stdscr.addstr(height - 2, 0, "─" * width)

        # Key help
        help_text = "S:Start X:Stop F3:Save F4:Reload TAB/←→:Switch PgUp/PgDn:Scroll Q/ESC:Quit"
        self.stdscr.addstr(height - 1, 2, help_text[:width-4])

    def draw_config_tab(self):
        """Draw configuration tab with scrolling support"""
        height, width = self.stdscr.getmaxyx()
        y = 4
        x = 2

        # Calculate shadow server URL
        shadow_url = f"opc.tcp://{self.config.get('udp_host', '0.0.0.0')}:{self.config.get('shadow_server_port', 4841)}/shadow"

        # Get encryption key with placeholder for empty value
        enc_key = self.config.get('encryption', {}).get('key', '')
        if enc_key:
            enc_key_display = enc_key[:40] + "..." if len(enc_key) > 40 else enc_key
        else:
            enc_key_display = "(empty - press ENTER to edit)"

        config_items = [
            ("UDP Listen Host", self.config.get('udp_host', '')),
            ("UDP Listen Port", str(self.config.get('udp_port', 5555))),
            ("Shadow Server Port", str(self.config.get('shadow_server_port', 4841))),
            ("Shadow Server Name", self.config.get('shadow_server_name', '')),
            ("Shadow Server URL", shadow_url),
            ("Encryption Enabled", "Yes" if self.config.get('encryption', {}).get('enabled', False) else "No"),
            ("Encryption Algorithm", self.config.get('encryption', {}).get('algorithm', 'aes-256-gcm') + " (available: aes-128/256-gcm, chacha20)"),
            ("Encryption Key", enc_key_display),
        ]

        # Calculate how many fields can fit on screen (each field takes 3 lines)
        available_height = height - 9  # Leave room for header and footer
        visible_fields = max(1, available_height // 3)

        # Adjust scroll offset to ensure current field is visible
        if self.current_field < self.scroll_offset:
            self.scroll_offset = self.current_field
        elif self.current_field >= self.scroll_offset + visible_fields:
            self.scroll_offset = self.current_field - visible_fields + 1

        # Clamp scroll offset
        max_scroll = max(0, len(config_items) - visible_fields)
        self.scroll_offset = max(0, min(self.scroll_offset, max_scroll))

        # Draw visible fields
        for i in range(self.scroll_offset, min(len(config_items), self.scroll_offset + visible_fields)):
            label, value = config_items[i]

            # Highlight current field
            attr = curses.color_pair(5) if i == self.current_field and self.current_tab == 0 else curses.A_NORMAL

            self.stdscr.addstr(y, x, f"{label}:", curses.color_pair(3) | curses.A_BOLD)
            self.stdscr.addstr(y + 1, x + 2, str(value)[:width-x-4], attr)
            y += 3

        # Show scroll indicator if needed
        if len(config_items) > visible_fields:
            scroll_info = f"[{self.scroll_offset + 1}-{min(self.scroll_offset + visible_fields, len(config_items))}/{len(config_items)}]"
            self.stdscr.addstr(height - 4, width - len(scroll_info) - 2, scroll_info, curses.color_pair(6))

    def draw_about_tab(self):
        """Draw about tab"""
        height, width = self.stdscr.getmaxyx()
        y = 5

        about_lines = [
            ("OPC UA Receiver - Shadow Server", curses.color_pair(3) | curses.A_BOLD),
            ("Version 1.0", curses.A_NORMAL),
            ("", curses.A_NORMAL),
            ("Copyright (C) 2026 Alin-Adrian Anton", curses.A_NORMAL),
            ("<alin.anton@upt.ro>", curses.color_pair(6)),
            ("", curses.A_NORMAL),
            ("This program is free software: you can redistribute it and/or modify", curses.A_NORMAL),
            ("it under the terms of the GNU General Public License as published by", curses.A_NORMAL),
            ("the Free Software Foundation, either version 3 of the License, or", curses.A_NORMAL),
            ("(at your option) any later version.", curses.A_NORMAL),
            ("", curses.A_NORMAL),
            ("This program is distributed in the hope that it will be useful,", curses.A_NORMAL),
            ("but WITHOUT ANY WARRANTY; without even the implied warranty of", curses.A_NORMAL),
            ("MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.", curses.A_NORMAL),
            ("", curses.A_NORMAL),
            ("See the GNU General Public License for more details:", curses.A_NORMAL),
            ("https://www.gnu.org/licenses/gpl-3.0.html", curses.color_pair(6) | curses.A_UNDERLINE),
        ]

        for line, attr in about_lines:
            if y >= height - 5:
                break
            if line:
                x = (width - len(line)) // 2
                self.stdscr.addstr(y, x, line, attr)
            y += 1

    def draw(self):
        """Draw the entire interface"""
        self.stdscr.clear()

        self.draw_header()

        if self.current_tab == 0:
            self.draw_config_tab()
        else:
            self.draw_about_tab()

        self.draw_status_line()

        self.stdscr.refresh()

    def edit_field(self, field_index):
        """Edit a configuration field"""
        height, width = self.stdscr.getmaxyx()

        fields = [
            'udp_host',
            'udp_port',
            'shadow_server_port',
            'shadow_server_name',
            'shadow_server_url',  # Read-only, skip editing
            'encryption.enabled',
            'encryption.algorithm',
            'encryption.key'
        ]

        if field_index >= len(fields):
            return

        field_name = fields[field_index]

        # Skip editing shadow_server_url (read-only)
        if field_name == 'shadow_server_url':
            self.status_message = "Shadow Server URL is read-only (auto-calculated)"
            return

        # Special handling for encryption algorithm - show options
        if field_name == 'encryption.algorithm':
            self.edit_algorithm_field()
            return

        # Get current value
        if '.' in field_name:
            parent, child = field_name.split('.')
            if child == 'enabled':
                current = self.config.get(parent, {}).get(child, False)
                # Toggle boolean
                self.config.setdefault(parent, {})[child] = not current
                self.status_message = f"Toggled {field_name}"
                return
            else:
                current = str(self.config.get(parent, {}).get(child, ''))
        else:
            current = str(self.config.get(field_name, ''))

        # Create edit window
        edit_win = curses.newwin(3, width - 20, height // 2 - 1, 10)
        edit_win.box()
        edit_win.addstr(0, 2, f" Edit {field_name} ", curses.color_pair(4) | curses.A_BOLD)

        # Input field
        input_win = edit_win.derwin(1, width - 24, 1, 2)
        input_win.addstr(0, 0, current[:width-26])

        edit_win.refresh()
        input_win.refresh()

        # Get input with ESC support
        curses.curs_set(1)
        input_win.move(0, 0)
        input_win.clrtoeol()
        input_win.addstr(0, 0, current[:width-26])
        input_win.move(0, len(current))
        input_win.refresh()

        # Manual input handling to support ESC
        new_value = list(current)
        pos = len(current)

        while True:
            ch = input_win.getch()

            if ch == 27:  # ESC - cancel
                curses.curs_set(0)
                self.status_message = "Edit cancelled"
                return
            elif ch in (curses.KEY_ENTER, 10, 13):  # Enter - accept
                break
            elif ch in (curses.KEY_BACKSPACE, 127, 8):  # Backspace
                if pos > 0:
                    new_value.pop(pos - 1)
                    pos -= 1
            elif ch == curses.KEY_DC:  # Delete
                if pos < len(new_value):
                    new_value.pop(pos)
            elif ch == curses.KEY_LEFT:
                if pos > 0:
                    pos -= 1
            elif ch == curses.KEY_RIGHT:
                if pos < len(new_value):
                    pos += 1
            elif ch == curses.KEY_HOME:
                pos = 0
            elif ch == curses.KEY_END:
                pos = len(new_value)
            elif 32 <= ch <= 126:  # Printable characters
                if len(new_value) < width - 26:
                    new_value.insert(pos, chr(ch))
                    pos += 1

            # Redraw input
            input_win.move(0, 0)
            input_win.clrtoeol()
            display_val = ''.join(new_value)[:width-26]
            input_win.addstr(0, 0, display_val)
            input_win.move(0, min(pos, width - 26 - 1))
            input_win.refresh()

        new_value = ''.join(new_value)
        curses.curs_set(0)

        # Update config
        if new_value or new_value == "":
            if '.' in field_name:
                parent, child = field_name.split('.')
                if field_name in ['udp_port', 'shadow_server_port']:
                    try:
                        self.config.setdefault(parent, {})[child] = int(new_value)
                    except ValueError:
                        self.status_message = "Invalid number"
                        return
                else:
                    self.config.setdefault(parent, {})[child] = new_value
            else:
                if field_name in ['udp_port', 'shadow_server_port']:
                    try:
                        self.config[field_name] = int(new_value)
                    except ValueError:
                        self.status_message = "Invalid number"
                        return
                else:
                    self.config[field_name] = new_value

            self.status_message = f"Updated {field_name}"

    def edit_algorithm_field(self):
        """Edit encryption algorithm with selection menu"""
        height, width = self.stdscr.getmaxyx()

        algorithms = ['aes-128-gcm', 'aes-256-gcm', 'chacha20-poly1305']
        descriptions = [
            'AES-128-GCM (fast, secure)',
            'AES-256-GCM (slower, more secure - RECOMMENDED)',
            'ChaCha20-Poly1305 (fastest, modern)'
        ]

        current_algo = self.config.get('encryption', {}).get('algorithm', 'aes-256-gcm')
        try:
            current_idx = algorithms.index(current_algo)
        except ValueError:
            current_idx = 1  # Default to aes-256-gcm

        # Create selection window
        menu_height = len(algorithms) + 4
        menu_width = max(len(d) for d in descriptions) + 4
        menu_win = curses.newwin(menu_height, menu_width, height // 2 - menu_height // 2, (width - menu_width) // 2)
        menu_win.keypad(True)  # Enable keypad for arrow keys

        selected = current_idx

        while True:
            menu_win.clear()
            menu_win.box()
            menu_win.addstr(0, 2, " Select Encryption Algorithm ", curses.color_pair(4) | curses.A_BOLD)

            # Draw menu options
            for i, desc in enumerate(descriptions):
                attr = curses.color_pair(5) | curses.A_BOLD if i == selected else curses.A_NORMAL
                menu_win.addstr(i + 2, 2, desc[:menu_width-4], attr)

            menu_win.refresh()

            key = menu_win.getch()

            if key == 27:  # ESC - cancel
                self.status_message = "Algorithm selection cancelled"
                return
            elif key in (curses.KEY_ENTER, 10, 13):  # Enter - accept
                self.config.setdefault('encryption', {})['algorithm'] = algorithms[selected]
                self.status_message = f"Algorithm set to {algorithms[selected]}"
                return
            elif key == curses.KEY_UP:
                selected = (selected - 1) % len(algorithms)
            elif key == curses.KEY_DOWN:
                selected = (selected + 1) % len(algorithms)

    def handle_input(self):
        """Handle keyboard input"""
        key = self.stdscr.getch()

        if key == -1:  # No input (timeout)
            return True
        elif key == 27:  # ESC key
            return False
        elif key == ord('q') or key == ord('Q'):
            return False
        elif key == ord('s') or key == ord('S') or key == curses.KEY_F1:
            self.start_receiver()
        elif key == ord('x') or key == ord('X') or key == curses.KEY_F2:
            self.stop_receiver()
        elif key == curses.KEY_F3:
            self.save_config()
        elif key == curses.KEY_F4:
            self.load_config()
            self.status_message = "Configuration reloaded"
        elif key == ord('\t') or key == 9:  # Tab
            self.current_tab = (self.current_tab + 1) % 2
            self.current_field = 0
        elif key == curses.KEY_LEFT:
            if self.current_tab == 1:  # In About tab, go back to Config
                self.current_tab = 0
                self.current_field = 0
        elif key == curses.KEY_RIGHT:
            if self.current_tab == 0:  # In Config tab, go to About
                self.current_tab = 1
        elif key == curses.KEY_UP:
            if self.current_tab == 0:
                self.current_field = (self.current_field - 1) % 8  # Wrap around (now 8 fields)
        elif key == curses.KEY_DOWN:
            if self.current_tab == 0:
                self.current_field = (self.current_field + 1) % 8  # Wrap around (now 8 fields)
        elif key == curses.KEY_PPAGE:  # Page Up
            if self.current_tab == 0:
                self.current_field = max(0, self.current_field - 3)
                self.scroll_offset = max(0, self.scroll_offset - 3)
        elif key == curses.KEY_NPAGE:  # Page Down
            if self.current_tab == 0:
                self.current_field = min(7, self.current_field + 3)
                self.scroll_offset = min(self.scroll_offset + 3, max(0, 8 - 1))
        elif key == ord('\n') or key == curses.KEY_ENTER or key == 10:
            if self.current_tab == 0:
                self.edit_field(self.current_field)

        return True

    def run(self):
        """Main run loop"""
        curses.curs_set(0)  # Hide cursor
        self.stdscr.keypad(True)
        self.stdscr.timeout(1000)  # 1 second timeout for getch()

        try:
            while True:
                self.draw()
                if not self.handle_input():
                    break

        finally:
            # Cleanup
            if self.is_running():
                self.stop_receiver()

def curses_main(stdscr):
    """Curses wrapper function"""
    app = ReceiverGUINCurses(stdscr)
    app.run()

def main():
    """Entry point for console script"""
    curses.wrapper(curses_main)

if __name__ == "__main__":
    main()
