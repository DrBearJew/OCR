#!/usr/bin/env python3
"""Offline launch regressions: no model weights, server process, or GPU required."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("serve", Path(__file__).resolve().parents[1] / "deploy/metadata/serve.py")
serve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serve)


class RuntimeTests(unittest.TestCase):
    def launch(self, environment):
        library = Mock()
        library.ggml_backend_cuda_get_device_count.return_value = 2
        library.ggml_backend_vk_get_device_count.return_value = 2
        with patch.dict(os.environ, environment, clear=True), \
                patch.object(serve.ctypes, "CDLL", return_value=library) as load_backend, \
                patch.object(serve, "ensure_model", return_value=Path("/models/test.gguf")) as provision, \
                patch.object(serve.os, "execv") as execute:
            serve.main()
        provision.assert_called_once_with("/models")
        if environment.get("DOKOCR_METADATA_COMPUTE", "cpu") == "cpu":
            load_backend.assert_not_called()
        else:
            load_backend.assert_called_once_with("libggml.so")
        executable, command = execute.call_args.args
        self.assertEqual(executable, command[0])
        self.assertEqual(command[command.index("--model") + 1], "/models/test.gguf")
        return command

    def test_default_and_explicit_cpu_disable_gpu(self):
        for environment in ({}, {"DOKOCR_METADATA_COMPUTE": "cpu"}):
            with self.subTest(environment=environment):
                command = self.launch(environment)
                self.assertEqual(command[command.index("--gpu-layers") + 1], "0")
                self.assertEqual(command[command.index("--device") + 1], "none")
                self.assertNotIn("--fit", command)

    def test_gpu_modes_fit_automatically(self):
        for compute in ("cuda", "vulkan"):
            with self.subTest(compute=compute):
                command = self.launch({"DOKOCR_METADATA_COMPUTE": compute})
                self.assertIn("--fit", command)
                self.assertNotIn("--gpu-layers", command)
                self.assertNotIn("--device", command)

    def test_explicit_layers_and_devices(self):
        for compute, devices in (("cuda", "CUDA0,CUDA1"), ("vulkan", "Vulkan1")):
            for layers in ("0", "24"):
                with self.subTest(compute=compute, layers=layers):
                    command = self.launch({"DOKOCR_METADATA_COMPUTE": compute,
                                           "DOKOCR_METADATA_GPU_LAYERS": layers,
                                           "DOKOCR_METADATA_DEVICES": devices,
                                           "DOKOCR_METADATA_THREADS": "6"})
                    self.assertEqual(command[command.index("--gpu-layers") + 1], layers)
                    self.assertNotIn("--fit", command)
                    self.assertEqual(command[command.index("--device") + 1], devices)
                    self.assertEqual(command.count("--device"), 1)
                    self.assertEqual(command[command.index("--threads") + 1], "6")

    def test_devices_with_fit(self):
        command = self.launch({"DOKOCR_METADATA_COMPUTE": "cuda", "DOKOCR_METADATA_DEVICES": "CUDA1"})
        self.assertIn("--fit", command)
        self.assertEqual(command[command.index("--device") + 1], "CUDA1")

    def test_invalid_config_precedes_provisioning(self):
        cases = [("DOKOCR_METADATA_COMPUTE", value) for value in ("", "CUDA", "rocm", "cpu\n")]
        cases += [("DOKOCR_METADATA_GPU_LAYERS", value) for value in ("", "-1", "1.5", "+1", " 1", "1\n", "2147483648")]
        cases += [("DOKOCR_METADATA_DEVICES", value) for value in ("", " ", "CUDA0\n", "CUDA0\r", "CUDA0\t", "CUDA0\x00")]
        cases += [("DOKOCR_METADATA_THREADS", value) for value in ("", "0", "-1", "oops")]
        for name, value in cases:
            with self.subTest(name=name, value=value), \
                    patch.object(serve.os, "environ", {"DOKOCR_METADATA_COMPUTE": "cuda", name: value}), \
                    patch.object(serve, "ensure_model") as provision, \
                    patch.object(serve.os, "execv") as execute:
                with self.assertRaisesRegex(ValueError, name):
                    serve.main()
                provision.assert_not_called()
                execute.assert_not_called()

    def test_cpu_rejects_gpu_only_options(self):
        for name, value in (("DOKOCR_METADATA_GPU_LAYERS", "12"), ("DOKOCR_METADATA_DEVICES", "CUDA0")):
            with self.subTest(name=name), patch.dict(os.environ, {name: value}, clear=True), \
                    patch.object(serve, "ensure_model") as provision:
                with self.assertRaisesRegex(ValueError, "requires.*cuda.*vulkan"):
                    serve.main()
                provision.assert_not_called()

    def test_unavailable_backend_or_device_precedes_provisioning(self):
        for compute in ("cuda", "vulkan"):
            for failure in ("library", "symbol", "no-devices", "wrong-device", "shell-text"):
                with self.subTest(compute=compute, failure=failure):
                    library = Mock()
                    backend = "cuda" if compute == "cuda" else "vk"
                    count = getattr(library, f"ggml_backend_{backend}_get_device_count")
                    count.return_value = 0 if failure == "no-devices" else 1
                    if failure == "symbol":
                        library = Mock(spec=[])
                    environment = {"DOKOCR_METADATA_COMPUTE": compute}
                    if failure in ("wrong-device", "shell-text"):
                        environment["DOKOCR_METADATA_DEVICES"] = "CUDA99" if failure == "wrong-device" else "CUDA0; touch /tmp/not-executed"
                    error = OSError("missing library") if failure == "library" else None
                    with patch.dict(os.environ, environment, clear=True), \
                            patch.object(serve.ctypes, "CDLL", return_value=library, side_effect=error), \
                            patch.object(serve, "ensure_model") as provision, \
                            patch.object(serve.os, "execv") as execute:
                        with self.assertRaisesRegex(RuntimeError, compute):
                            serve.main()
                        provision.assert_not_called()
                        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
