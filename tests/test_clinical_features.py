import os
import tempfile
import unittest

import numpy as np
import soundfile as sf

import gradio_app


class ClinicalFeatureTests(unittest.TestCase):
    def _wav(self, samples, sample_rate=22050):
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        sf.write(path, samples, sample_rate)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def test_quality_validator_accepts_clear_recording(self):
        sample_rate = 22050
        time = np.arange(sample_rate * 2) / sample_rate
        path = self._wav((0.12 * np.sin(2 * np.pi * 440 * time)).astype(np.float32))
        quality = gradio_app.validate_audio_quality(path)
        self.assertFalse(quality["blocking"])
        self.assertEqual(quality["status"], "good")

    def test_quality_validator_blocks_silent_recording(self):
        path = self._wav(np.zeros(22050, dtype=np.float32))
        quality = gradio_app.validate_audio_quality(path)
        self.assertTrue(quality["blocking"])
        self.assertEqual(quality["status"], "poor")

    def test_model_comparison_returns_compatible_models(self):
        preprocessor = gradio_app.load_preprocessor()
        dataframe = gradio_app.build_input_dataframe(
            "public_dataset/00ccf4e3-6e4f-4e6b-a16d-11b4a8999d1e.webm",
            "unknown", 30, 0.5, False, False, preprocessor,
        )
        rows = gradio_app.compare_models(
            preprocessor.transform(dataframe),
            gradio_app.compatible_model_files(preprocessor, gradio_app.list_available_models()),
        )
        self.assertGreaterEqual(len(rows), 3)
        self.assertTrue(all(0 <= row["confidence"] <= 1 for row in rows))


if __name__ == "__main__":
    unittest.main()
