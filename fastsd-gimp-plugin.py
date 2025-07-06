#!/usr/bin/env python3
# Copyright(C) 2025 Rupesh Sreeraman

import gi

gi.require_version("Gimp", "3.0")
from gi.repository import Gimp, Gio, GLib

gi.require_version("GimpUi", "3.0")
from gi.repository import GimpUi
import sys
import tempfile
import os
import tempfile
from http import client
import json
from base64 import b64decode
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

FASTSD_SERVER_URL = "http://localhost:8000"


class FastSDRequests:
    def __init__(self, server_url=FASTSD_SERVER_URL):
        self.server_url = server_url
        self.url = urlparse(self.server_url)

    def get_request(self, url) -> dict:
        try:
            conn = client.HTTPConnection(self.url.hostname, self.url.port)
            headers = {"Content-Type": "application/json"}
            conn.request(
                "GET",
                url,
                body=None,
                headers=headers,
            )
            res = conn.getresponse()
            data = res.read()
            result = json.loads(data)
            return result
        except Exception as exception:
            raise Exception(f"Error: {str(exception)}")

    def load_settings(self) -> dict:
        """Loads settings from the FastSD server."""
        try:
            config = self.get_request("/api/config")
            return config
        except Exception as exception:
            raise RuntimeError("Failed to get settings!") from exception

    def get_info(self) -> dict:
        """
        Returns information about the FastSD server
        """
        try:
            result = self.get_request("/api/info")
            return result
        except Exception as exception:
            raise RuntimeError("Failed to get info from FastSD") from exception

    def get_models(self) -> list:
        """
        Returns a list of available models.
        """
        try:
            result = self.get_request("/api/models")
            return result["openvino_models"]
        except Exception as exception:
            raise RuntimeError("Failed to get models from API") from exception

    def generate_text_to_image(self, config) -> dict:
        """Generates an image based on the provided configuration."""
        conn = client.HTTPConnection(self.url.hostname, self.url.port)
        headers = {"Content-Type": "application/json"}
        conn.request("POST", "/api/generate", config, headers)
        res = conn.getresponse()
        data = res.read()
        result = json.loads(data)
        return result


class FastSDPlugin(Gimp.PlugIn):
    def do_query_procedures(self):
        return ["fastsd-plugin"]

    def generate_image(self, config):
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    self.fast_sd_requests.generate_text_to_image,
                    config,
                )
                result = future.result()
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                temp_file_path = temp_file.name
                base64_image = result["images"][0]
                image_data = b64decode(base64_image)
                temp_file.write(image_data)
                temp_file.close()
            return temp_file_path

        except Exception as exception:
            raise RuntimeError("Failed to generate image ") from exception

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None
        )
        procedure.set_image_types("*")
        procedure.set_menu_label("generate image")
        procedure.add_menu_path("<Image>/Layer/FastSD")
        procedure.set_documentation(
            "fastsd-plugin",
            "Generates an image using FastSD and adds it as a new layer.",
            name,
        )
        procedure.set_attribution("Rupesh Sreeraman", "FastSD", "2025")
        return procedure

    def find_index_by_text(self, combo, target_text):
        index = 0
        model = combo.get_model()
        for row in model:
            if row[0] == target_text:
                return index
            index += 1
        return -1  # Not found

    def init_ui_settings(self):
        try:
            self.settings = self.fast_sd_requests.load_settings()
        except RuntimeError as exp:
            self.settings = {}
        try:
            self.models = self.fast_sd_requests.get_models()
        except RuntimeError as exp:
            self.models = []

    def run(
        self,
        procedure,
        run_mode,
        image,
        drawables,
        config,
        run_data,
    ):
        self.fast_sd_requests = FastSDRequests()
        self.file_path = None
        try:
            self.info = self.fast_sd_requests.get_info()

        except RuntimeError as exp:
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR,
                GLib.Error.new_literal(
                    domain=GLib.quark_from_string("my-plugin-domain"),
                    code=1,
                    message=f"Ensure that FastSD server is running at {FASTSD_SERVER_URL}.\n{str(exp)}",
                ),
            )

        self.init_ui_settings()
        diffusion_setting = self.settings.get("lcm_diffusion_setting", {})
        model_id = diffusion_setting.get("openvino_lcm_model_id", "")
        inference_steps = diffusion_setting.get("inference_steps", 1)
        img_height = diffusion_setting.get("image_height", 512)
        img_width = diffusion_setting.get("image_width", 512)

        if run_mode == Gimp.RunMode.INTERACTIVE:
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk

            GimpUi.init("fastsd-plugin")

            dialog = GimpUi.Dialog(
                title="FastSD Plugin",
                role="fastsd-plugin",
                use_header_bar=False,
            )
            dialog.set_default_size(400, 400)
            dialog.set_resizable(False)

            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            vbox.set_margin_top(10)
            vbox.set_margin_bottom(10)
            vbox.set_margin_start(10)
            vbox.set_margin_end(10)

            device_label = Gtk.Label(
                label=f"{self.info.get('device_type', '').upper()} : {self.info.get('device_name', '')}"
            )

            vbox.pack_start(device_label, False, False, 0)

            prompt_label = Gtk.Label(label="Describe the image you want to generate :")
            prompt_label.set_halign(Gtk.Align.START)
            prompt_label.set_valign(Gtk.Align.CENTER)
            vbox.pack_start(prompt_label, False, False, 0)
            textview = Gtk.TextView()
            textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            textview.set_size_request(-1, 50)  # Set a reasonable height
            vbox.pack_start(textview, False, False, 0)

            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            vbox.pack_start(hbox, False, False, 0)

            generate_button = Gtk.Button(label="Generate")
            generate_button.set_size_request(100, -1)
            hbox.pack_start(Gtk.Label(), True, True, 0)  # Expanding empty label
            hbox.pack_start(generate_button, False, False, 0)

            model_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

            model_label = Gtk.Label(label="Model:")
            model_label.set_halign(Gtk.Align.START)
            model_label.set_valign(Gtk.Align.CENTER)
            model_box.pack_start(model_label, False, False, 0)

            model_combo = Gtk.ComboBoxText()

            for model in self.models:
                model_combo.append_text(model)

            if model_id in self.models:
                index = self.models.index(model_id)
                model_combo.set_active(index)
            else:
                model_combo.set_active(0)

            model_box.pack_start(model_combo, True, True, 0)

            vbox.pack_start(model_box, False, False, 0)

            inference_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

            inference_label = Gtk.Label(label="Inference Steps:")
            inference_label.set_halign(Gtk.Align.START)
            inference_label.set_valign(Gtk.Align.CENTER)
            inference_box.pack_start(inference_label, False, False, 0)

            inference_scale = Gtk.Scale.new_with_range(
                Gtk.Orientation.HORIZONTAL, 1, 20, 1
            )
            inference_scale.set_value(inference_steps)
            inference_scale.set_digits(0)
            inference_scale.set_hexpand(True)
            inference_box.pack_start(inference_scale, True, True, 0)

            vbox.pack_start(inference_box, False, False, 0)

            width_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

            width_label = Gtk.Label(label="Width:")
            width_label.set_halign(Gtk.Align.START)
            width_label.set_valign(Gtk.Align.CENTER)
            width_box.pack_start(width_label, False, False, 0)

            width_combo = Gtk.ComboBoxText()
            width_combo.append_text("256")
            width_combo.append_text("512")
            width_combo.append_text("768")
            width_combo.append_text("1024")
            width_combo.set_active(self.find_index_by_text(width_combo, str(img_width)))
            width_box.pack_start(width_combo, True, True, 0)

            height_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

            height_label = Gtk.Label(label="Height:")
            height_label.set_halign(Gtk.Align.START)
            height_label.set_valign(Gtk.Align.CENTER)
            height_box.pack_start(height_label, False, False, 0)

            height_combo = Gtk.ComboBoxText()
            height_combo.append_text("256")
            height_combo.append_text("512")
            height_combo.append_text("768")
            height_combo.append_text("1024")
            height_combo.set_active(
                self.find_index_by_text(height_combo, str(img_height))
            )
            height_box.pack_start(height_combo, True, True, 0)

            vbox.pack_start(inference_box, False, False, 0)
            vbox.pack_start(width_box, False, False, 0)
            vbox.pack_start(height_box, False, False, 0)

            def on_generate_clicked(button):
                user_input = textview.get_buffer().get_text(
                    textview.get_buffer().get_start_iter(),
                    textview.get_buffer().get_end_iter(),
                    False,
                )

                inference_steps = int(inference_scale.get_value())
                selected_model = model_combo.get_active_text()
                config = json.dumps(
                    {
                        "prompt": user_input,
                        "inference_steps": inference_steps,
                        "use_openvino": True,
                        "use_tiny_auto_encoder": False,
                        "openvino_lcm_model_id": selected_model,
                        "image_width": img_width,
                        "image_height": img_height,
                    }
                )
                self.file_path = self.generate_image(config)

                if not os.path.exists(self.file_path):
                    Gimp.message(f"File not found:\n{self.file_path}")
                    return procedure.new_return_values(
                        Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error()
                    )

                try:
                    gfile = Gio.File.new_for_path(self.file_path)
                    new_layer = Gimp.file_load_layer(
                        Gimp.RunMode.NONINTERACTIVE, image, gfile
                    )

                    if not new_layer:
                        Gimp.message("Failed to load image.")
                        return procedure.new_return_values(
                            Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error()
                        )

                    image.insert_layer(new_layer, None, 0)
                    new_layer.set_name(os.path.basename(self.file_path))
                    Gimp.displays_flush()

                except Exception as e:
                    Gimp.message(f"Error loading image: {e}")
                    return procedure.new_return_values(
                        Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error()
                    )

            generate_button.connect("clicked", on_generate_clicked)

            dialog.get_content_area().add(vbox)
            dialog.show_all()

            _ = dialog.run()
            dialog.destroy()

        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


Gimp.main(FastSDPlugin.__gtype__, sys.argv)
