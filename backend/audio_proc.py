import logging
import os
import tempfile
from typing import Optional
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

# --- Configuration ---
MODEL_SIZE = os.environ.get("WHISPER_MODEL", "base")
DEVICE = os.environ.get("WHISPER_DEVICE", "cpu") # or "cuda"
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE", "int8")

class STTProcessor:
    def __init__(self):
        self.model = None
        self._initialized = False

    def _initialize(self):
        if self._initialized:
            return
        try:
            logger.info(f"Loading Whisper model: {MODEL_SIZE} on {DEVICE}...")
            # We use local_files_only=False to allow download on first run
            self.model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
            self._initialized = True
            logger.info("Whisper model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")

    def transcribe(self, audio_bytes: bytes) -> Optional[str]:
        """Transcribes audio bytes to text."""
        if not self._initialized:
            self._initialize()
        
        if not self.model:
            return None

        # Whisper needs a file path
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            segments, info = self.model.transcribe(tmp_path, beam_size=5)
            text = " ".join([segment.text for segment in segments])
            return text.strip()
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return None
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

# Singleton
stt_processor = STTProcessor()

def transcribe_audio(audio_data: bytes) -> str:
    result = stt_processor.transcribe(audio_data)
    return result or ""
