#!/usr/bin/env python3
"""
OPC UA Receiver GUI - Graphical interface for receiver_auto.py
Supports both Tkinter (graphical) and terminal modes

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
import tkinter as tk
from tkinter import ttk, messagebox
import json
import subprocess
import sys
import os
from PIL import Image, ImageTk

class ReceiverGUI:
    def __init__(self, root, config_file='receiver_config.json'):
        self.root = root
        self.root.title("OPC UA Receiver - Shadow Server")
        self.root.geometry("900x650")

        self.config_file = config_file
        self.config = {}
        self.process = None
        self.log_file = None

        # Load and resize status indicator images
        self.load_status_images()

        self.load_config()
        self.create_widgets()

    def load_status_images(self):
        """Load and resize red/green status indicator images"""
        try:
            # Get the directory where this script is located
            script_dir = os.path.dirname(os.path.abspath(__file__))
            red_path = os.path.join(script_dir, 'red.png')
            green_path = os.path.join(script_dir, 'green.png')

            # Load images and resize to 40x40
            red_img = Image.open(red_path).resize((40, 40), Image.LANCZOS)
            green_img = Image.open(green_path).resize((40, 40), Image.LANCZOS)

            # Convert to PhotoImage
            self.red_image = ImageTk.PhotoImage(red_img)
            self.green_image = ImageTk.PhotoImage(green_img)
        except Exception as e:
            print(f"Warning: Could not load status images: {e}")
            # Fallback to None, will handle in UI
            self.red_image = None
            self.green_image = None

    def load_config(self):
        """Load configuration from JSON file"""
        try:
            with open(self.config_file, 'r') as f:
                self.config = json.load(f)
        except FileNotFoundError:
            messagebox.showerror("Error", f"Config file not found: {self.config_file}")
            self.config = self.get_default_config()
        except json.JSONDecodeError as e:
            messagebox.showerror("Error", f"Invalid JSON in config: {e}")
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
            messagebox.showinfo("Success", "Configuration saved successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save config: {e}")

    def create_widgets(self):
        """Create GUI widgets"""
        # Create notebook for tabs
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Configuration tab
        config_frame = ttk.Frame(notebook)
        notebook.add(config_frame, text="Configuration")
        self.create_config_widgets(config_frame)

        # About tab
        about_frame = ttk.Frame(notebook)
        notebook.add(about_frame, text="About")
        self.create_about_widgets(about_frame)

        # Control buttons at bottom
        control_frame = ttk.Frame(self.root)
        control_frame.pack(fill=tk.X, padx=5, pady=5)

        self.start_btn = ttk.Button(control_frame, text="Start Receiver", command=self.start_receiver)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(control_frame, text="Stop Receiver", command=self.stop_receiver, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        ttk.Button(control_frame, text="Save Config", command=self.save_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Reload Config", command=self.reload_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="About", command=self.show_about).pack(side=tk.LEFT, padx=5)

        self.status_label = ttk.Label(control_frame, text="Status: Stopped", foreground="red")
        self.status_label.pack(side=tk.RIGHT, padx=5)

    def create_config_widgets(self, parent):
        """Create configuration widgets"""
        # Scrollable frame
        canvas = tk.Canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # UDP settings
        ttk.Label(scrollable_frame, text="UDP Settings", font=('Arial', 12, 'bold')).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=10)

        ttk.Label(scrollable_frame, text="UDP Listen Host:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.udp_host_var = tk.StringVar(value=self.config.get('udp_host', '0.0.0.0'))
        ttk.Entry(scrollable_frame, textvariable=self.udp_host_var, width=50).grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)

        ttk.Label(scrollable_frame, text="UDP Listen Port:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.udp_port_var = tk.IntVar(value=self.config.get('udp_port', 5555))
        ttk.Entry(scrollable_frame, textvariable=self.udp_port_var, width=50).grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)

        # Shadow Server settings
        ttk.Label(scrollable_frame, text="Shadow Server Settings", font=('Arial', 12, 'bold')).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=10)

        ttk.Label(scrollable_frame, text="Shadow Server Port:").grid(row=4, column=0, sticky=tk.W, padx=5, pady=2)
        self.shadow_port_var = tk.IntVar(value=self.config.get('shadow_server_port', 4841))
        ttk.Entry(scrollable_frame, textvariable=self.shadow_port_var, width=50).grid(row=4, column=1, sticky=tk.W, padx=5, pady=2)

        ttk.Label(scrollable_frame, text="Shadow Server Name:").grid(row=5, column=0, sticky=tk.W, padx=5, pady=2)
        self.shadow_name_var = tk.StringVar(value=self.config.get('shadow_server_name', 'Shadow OPC UA Server'))
        ttk.Entry(scrollable_frame, textvariable=self.shadow_name_var, width=50).grid(row=5, column=1, sticky=tk.W, padx=5, pady=2)

        # Display Shadow Server URL
        shadow_url = f"opc.tcp://{self.config.get('udp_host', '0.0.0.0')}:{self.config.get('shadow_server_port', 4841)}/shadow"
        ttk.Label(scrollable_frame, text="Shadow Server URL:", font=('Arial', 10, 'bold')).grid(row=6, column=0, sticky=tk.W, padx=5, pady=2)
        self.shadow_url_label = ttk.Label(scrollable_frame, text=shadow_url, foreground='blue', font=('Arial', 9))
        self.shadow_url_label.grid(row=6, column=1, sticky=tk.W, padx=5, pady=2)

        # Encryption settings
        ttk.Label(scrollable_frame, text="Encryption Settings", font=('Arial', 12, 'bold')).grid(row=7, column=0, columnspan=2, sticky=tk.W, pady=10)

        self.encrypt_enabled_var = tk.BooleanVar(value=self.config.get('encryption', {}).get('enabled', False))
        ttk.Checkbutton(scrollable_frame, text="Enable Encryption", variable=self.encrypt_enabled_var).grid(row=8, column=0, columnspan=2, sticky=tk.W, padx=5, pady=2)

        ttk.Label(scrollable_frame, text="Algorithm:").grid(row=9, column=0, sticky=tk.W, padx=5, pady=2)
        self.encrypt_algo_var = tk.StringVar(value=self.config.get('encryption', {}).get('algorithm', 'aes-256-gcm'))
        algo_combo = ttk.Combobox(scrollable_frame, textvariable=self.encrypt_algo_var,
                                   values=['aes-128-gcm', 'aes-256-gcm', 'chacha20-poly1305'],
                                   state='readonly', width=47)
        algo_combo.grid(row=9, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(scrollable_frame, text="Available: aes-128-gcm (fast), aes-256-gcm (recommended), chacha20-poly1305 (fastest)",
                 foreground='gray', font=('Arial', 8)).grid(row=10, column=1, sticky=tk.W, padx=5, pady=0)

        ttk.Label(scrollable_frame, text="Encryption Key:").grid(row=11, column=0, sticky=tk.W, padx=5, pady=(5,2))
        self.encrypt_key_var = tk.StringVar(value=self.config.get('encryption', {}).get('key', ''))
        self.key_entry = ttk.Entry(scrollable_frame, textvariable=self.encrypt_key_var, width=50, show="*")
        self.key_entry.grid(row=11, column=1, sticky=tk.W, padx=5, pady=(5,2))

        key_buttons_frame = ttk.Frame(scrollable_frame)
        key_buttons_frame.grid(row=12, column=1, sticky=tk.W, padx=5, pady=2)
        self.show_key_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(key_buttons_frame, text="Show Key", variable=self.show_key_var, command=self.toggle_key_visibility).pack(side=tk.LEFT)

        ttk.Label(scrollable_frame, text="Note: Encryption key must match sender's key", foreground="blue").grid(row=13, column=0, columnspan=2, sticky=tk.W, padx=5, pady=5)

        # Visual status indicator
        ttk.Label(scrollable_frame, text="Status Indicator:", font=('Arial', 12, 'bold')).grid(row=14, column=0, columnspan=2, sticky=tk.W, pady=(20, 10))

        indicator_frame = ttk.Frame(scrollable_frame)
        indicator_frame.grid(row=15, column=0, columnspan=2, padx=5, pady=5, sticky=tk.W)

        # Status indicator using image
        if self.red_image and self.green_image:
            self.status_image_label = tk.Label(indicator_frame, image=self.red_image, cursor='hand2')
            self.status_image_label.pack(side=tk.LEFT, padx=10)
            # Bind click event to toggle start/stop
            self.status_image_label.bind('<Button-1>', self.toggle_receiver)
        else:
            # Fallback to canvas if images not available
            self.status_canvas = tk.Canvas(indicator_frame, width=60, height=60, bg='white', highlightthickness=1, highlightbackground='gray', cursor='hand2')
            self.status_canvas.pack(side=tk.LEFT, padx=10)
            self.status_circle = self.status_canvas.create_oval(10, 10, 50, 50, fill='red', outline='darkgray', width=2)
            self.status_canvas.bind('<Button-1>', self.toggle_receiver)

        status_text_frame = ttk.Frame(indicator_frame)
        status_text_frame.pack(side=tk.LEFT, padx=10)
        self.status_text_label = ttk.Label(status_text_frame, text="Stopped", font=('Arial', 10, 'bold'))
        self.status_text_label.pack(anchor=tk.W)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def create_about_widgets(self, parent):
        """Create About tab widgets"""
        import webbrowser

        # Main frame with padding
        main_frame = ttk.Frame(parent, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Title
        title_label = ttk.Label(main_frame, text="OPC UA Receiver - Shadow Server",
                                font=('Arial', 14, 'bold'))
        title_label.pack(pady=(0, 5))

        version_label = ttk.Label(main_frame, text="Version 1.0", font=('Arial', 10))
        version_label.pack(pady=(0, 15))

        # Copyright
        copyright_label = ttk.Label(main_frame, text="Copyright (C) 2026 Alin-Adrian Anton",
                                    font=('Arial', 10))
        copyright_label.pack(pady=(0, 2))

        email_label = ttk.Label(main_frame, text="<alin.anton@upt.ro>",
                               font=('Arial', 9), foreground='blue')
        email_label.pack(pady=(0, 15))

        # License text
        license_text = """This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

See the GNU General Public License for more details:"""

        license_label = ttk.Label(main_frame, text=license_text,
                                 font=('Arial', 9), justify=tk.LEFT)
        license_label.pack(pady=(0, 10))

        # Clickable link
        link_label = ttk.Label(main_frame, text="https://www.gnu.org/licenses/gpl-3.0.html",
                              font=('Arial', 9, 'underline'), foreground='blue', cursor='hand2')
        link_label.pack(pady=(0, 15))
        link_label.bind('<Button-1>', lambda e: webbrowser.open('https://www.gnu.org/licenses/gpl-3.0.html'))

    def show_about(self):
        """Show About dialog with clickable link"""
        import webbrowser

        about_window = tk.Toplevel(self.root)
        about_window.title("About OPC UA Receiver")
        about_window.geometry("500x400")
        about_window.resizable(False, False)

        # Center the window
        about_window.transient(self.root)
        about_window.grab_set()

        # Main frame with padding
        main_frame = ttk.Frame(about_window, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Title
        title_label = ttk.Label(main_frame, text="OPC UA Receiver - Shadow Server",
                                font=('Arial', 14, 'bold'))
        title_label.pack(pady=(0, 5))

        version_label = ttk.Label(main_frame, text="Version 1.0", font=('Arial', 10))
        version_label.pack(pady=(0, 15))

        # Copyright
        copyright_label = ttk.Label(main_frame, text="Copyright (C) 2026 Alin-Adrian Anton",
                                    font=('Arial', 10))
        copyright_label.pack(pady=(0, 2))

        email_label = ttk.Label(main_frame, text="<alin.anton@upt.ro>",
                               font=('Arial', 9), foreground='blue')
        email_label.pack(pady=(0, 15))

        # License text
        license_text = """This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

See the GNU General Public License for more details:"""

        license_label = ttk.Label(main_frame, text=license_text,
                                 font=('Arial', 9), justify=tk.LEFT)
        license_label.pack(pady=(0, 10))

        # Clickable link
        link_label = ttk.Label(main_frame, text="https://www.gnu.org/licenses/gpl-3.0.html",
                              font=('Arial', 9, 'underline'), foreground='blue', cursor='hand2')
        link_label.pack(pady=(0, 15))
        link_label.bind('<Button-1>', lambda e: webbrowser.open('https://www.gnu.org/licenses/gpl-3.0.html'))

        # Close button
        close_btn = ttk.Button(main_frame, text="Close", command=about_window.destroy, width=20)
        close_btn.pack(pady=10)

    def toggle_key_visibility(self):
        """Toggle encryption key visibility"""
        if self.show_key_var.get():
            self.key_entry.config(show="")
        else:
            self.key_entry.config(show="*")

    def update_status_indicator(self, running):
        """Update visual status indicator"""
        if hasattr(self, 'status_image_label'):
            # Using image-based indicator
            if running:
                self.status_image_label.config(image=self.green_image)
            else:
                self.status_image_label.config(image=self.red_image)
        elif hasattr(self, 'status_canvas'):
            # Fallback to canvas-based indicator
            if running:
                self.status_canvas.itemconfig(self.status_circle, fill='green')
            else:
                self.status_canvas.itemconfig(self.status_circle, fill='red')

    def toggle_receiver(self, event=None):
        """Toggle receiver on/off when clicking the status indicator"""
        if self.process and self.process.poll() is None:
            # Process is running, stop it
            self.stop_receiver()
        else:
            # Process is not running, start it
            self.start_receiver()

    def reload_config(self):
        """Reload configuration from file"""
        self.load_config()
        # Update all variables
        self.udp_host_var.set(self.config.get('udp_host', '0.0.0.0'))
        self.udp_port_var.set(self.config.get('udp_port', 5555))
        self.shadow_port_var.set(self.config.get('shadow_server_port', 4841))
        self.shadow_name_var.set(self.config.get('shadow_server_name', 'Shadow OPC UA Server'))
        self.encrypt_enabled_var.set(self.config.get('encryption', {}).get('enabled', False))
        self.encrypt_algo_var.set(self.config.get('encryption', {}).get('algorithm', 'aes-256-gcm'))
        self.encrypt_key_var.set(self.config.get('encryption', {}).get('key', ''))
        messagebox.showinfo("Success", "Configuration reloaded successfully!")

    def update_config_from_gui(self):
        """Update config dictionary from GUI values"""
        self.config['udp_host'] = self.udp_host_var.get()
        self.config['udp_port'] = self.udp_port_var.get()
        self.config['shadow_server_port'] = self.shadow_port_var.get()
        self.config['shadow_server_name'] = self.shadow_name_var.get()
        self.config['encryption'] = {
            'enabled': self.encrypt_enabled_var.get(),
            'algorithm': self.encrypt_algo_var.get(),
            'key': self.encrypt_key_var.get()
        }

    def start_receiver(self):
        """Start the receiver process"""
        if self.process and self.process.poll() is None:
            messagebox.showwarning("Warning", "Receiver is already running!")
            return

        # Update and save config
        self.update_config_from_gui()
        self.save_config()

        # Start process with output redirected to log file
        try:
            log_file = open('receiver_auto.log', 'w')
            self.log_file = log_file

            self.process = subprocess.Popen(
                ['opcua-receiver', self.config_file],
                stdout=log_file,
                stderr=subprocess.STDOUT
            )

            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
            self.status_label.config(text="Status: Running", foreground="green")
            self.status_text_label.config(text="Running")
            self.update_status_indicator(True)

            # Monitor process status
            self.monitor_process()

        except Exception as e:
            messagebox.showerror("Error", f"Failed to start receiver: {e}")

    def stop_receiver(self):
        """Stop the receiver process"""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

            self.process = None

            # Close log file
            if hasattr(self, 'log_file') and self.log_file:
                self.log_file.close()
                self.log_file = None

            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
            self.status_label.config(text="Status: Stopped", foreground="red")
            self.status_text_label.config(text="Stopped")
            self.update_status_indicator(False)

    def monitor_process(self):
        """Monitor if process is still running"""
        if not self.process or self.process.poll() is not None:
            if self.process:
                self.start_btn.config(state=tk.NORMAL)
                self.stop_btn.config(state=tk.DISABLED)
                self.status_label.config(text="Status: Stopped", foreground="red")
                self.status_text_label.config(text="Stopped")
                self.update_status_indicator(False)
                if hasattr(self, 'log_file') and self.log_file:
                    self.log_file.close()
                    self.log_file = None
                self.process = None
            return

        # Schedule next check (every 2 seconds)
        self.root.after(2000, self.monitor_process)

def main():
    root = tk.Tk()
    app = ReceiverGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
