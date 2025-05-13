import base64
import logging
import os
from typing import Any, Dict, Optional

import assemblyai as aai
import cv2
import litellm
import tomli

from core.config import get_settings
from core.models.video import ParseVideoResult, TimeSeriesData

logger = logging.getLogger(__name__)
litellm.drop_params = True

def debug_object(title, obj):
    logger.debug("\n".join(["-" * 100, title, "-" * 100, f"{obj}", "-" * 100]))


def load_config() -> Dict[str, Any]:
    config_path = os.path.join(os.path.dirname(__file__), "../../../morphik.toml")
    with open(config_path, "rb") as f:
        return tomli.load(f)


class VisionModelClient:
    def __init__(self, config: Dict[str, Any]):
        self.config = config["parser"]["vision"]
        self.model_key = self.config.get("model")
        self.settings = get_settings()

        # Get the model configuration from registered_models
        if not hasattr(self.settings, "REGISTERED_MODELS") or self.model_key not in self.settings.REGISTERED_MODELS:
            raise ValueError(f"Model '{self.model_key}' not found in registered_models configuration")

        self.model_config = self.settings.REGISTERED_MODELS[self.model_key]
        logger.info(f"Initialized VisionModelClient with model_key={self.model_key}, config={self.model_config}")

        # Check if the model has vision capability
        if not self.model_config.get("vision", False):
            logger.warning(f"Model '{self.model_key}' does not have vision capability marked in config")

    async def get_frame_description(self, image_base64: str, context: str) -> str:
        # Create a system message
        system_message = {
            "role": "system",
            "content": "You are a video frame description assistant. Describe the frame clearly and concisely.",
        }

        # Determine if the model is OpenAI compatible or Ollama compatible based on model name
        model_name = self.model_config.get("model_name", "")

        if "ollama" in model_name.lower():
            # Ollama format with images parameter
            messages = [system_message, {"role": "user", "content": context}]

            model_params = {"model": model_name, "messages": messages, "images": [image_base64]}
        else:
            # Standard format with image_url (OpenAI, Anthropic, etc.)
            messages = [
                system_message,
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": context},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                        },
                    ],
                },
            ]

            model_params = {
                "model": model_name,
                "messages": messages,
                "max_tokens": 300,
            }

        # Add all additional parameters from the model config
        for key, value in self.model_config.items():
            if key not in ["model_name", "vision"]:
                model_params[key] = value

        # Use litellm for the completion
        response = await litellm.acompletion(**model_params)
        return response.choices[0].message.content


class VideoParser:
    def __init__(self, video_path: str, assemblyai_api_key: str, frame_sample_rate: Optional[int] = None):
        """
        Initialize the video parser

        Args:
            video_path: Path to the video file
            assemblyai_api_key: API key for AssemblyAI
            frame_sample_rate: Sample every nth frame for description (optional, defaults to config value)
        """
        logger.info(f"Initializing VideoParser for {video_path}")
        self.config = load_config()
        self.video_path = video_path
        self.frame_sample_rate = frame_sample_rate or self.config["parser"]["vision"].get("frame_sample_rate", 120)
        self.cap = cv2.VideoCapture(video_path)

        if not self.cap.isOpened():
            logger.error(f"Failed to open video file: {video_path}")
            raise ValueError(f"Could not open video file: {video_path}")

        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.duration = self.total_frames / self.fps

        # Initialize AssemblyAI
        aai.settings.api_key = assemblyai_api_key
        aai_config = aai.TranscriptionConfig(speaker_labels=True)
        self.transcriber = aai.Transcriber(config=aai_config)
        self.transcript = TimeSeriesData(time_to_content={})

        # Initialize vision model client
        self.vision_client = VisionModelClient(self.config)

        logger.info(f"Video loaded: {self.duration:.2f}s duration, {self.fps:.2f} FPS")

    def frame_to_base64(self, frame) -> str:
        """Convert a frame to base64 string"""
        success, buffer = cv2.imencode(".jpg", frame)
        if not success:
            logger.error("Failed to encode frame to JPEG")
            raise ValueError("Failed to encode frame")
        return base64.b64encode(buffer).decode("utf-8")

    def get_transcript_object(self) -> aai.Transcript:
        """
        Get the transcript object from AssemblyAI
        """
        logger.info("Starting video transcription")
        transcript = self.transcriber.transcribe(self.video_path)
        if transcript.status == "error":
            logger.error(f"Transcription failed: {transcript.error}")
            raise ValueError(f"Transcription failed: {transcript.error}")
        if not transcript.words:
            logger.warning("No words found in transcript")
        logger.info("Transcription completed successfully!")

        return transcript

    def get_transcript(self) -> TimeSeriesData:
        """
        Get timestamped transcript of the video using AssemblyAI

        Returns:
            TimeSeriesData object containing transcript
        """
        logger.info("Starting video transcription")
        transcript = self.get_transcript_object()
        # divide by 1000 because assemblyai timestamps are in milliseconds
        time_to_text = {u.start / 1000: u.text for u in transcript.utterances} if transcript.utterances else {}
        debug_object("Time to text", time_to_text)
        self.transcript = TimeSeriesData(time_to_content=time_to_text)
        return self.transcript

    async def get_frame_descriptions(self) -> TimeSeriesData:
        """
        Get descriptions for sampled frames using configured vision model

        Returns:
            TimeSeriesData object containing frame descriptions
        """
        logger.info("Starting frame description generation")

        # Return empty TimeSeriesData if frame_sample_rate is -1 (captioning disabled)
        if self.frame_sample_rate == -1:
            logger.info("Frame captioning is disabled (frame_sample_rate = -1)")
            return TimeSeriesData(time_to_content={})

        frame_count = 0
        time_to_description = {}
        last_description = None
        logger.info("Starting main loop for frame description generation")
        while True:
            logger.info(f"Frame count: {frame_count}")
            ret, frame = self.cap.read()
            if not ret:
                logger.info("Reached end of video")
                break

            if frame_count % self.frame_sample_rate == 0:
                logger.info(f"Processing frame at {frame_count / self.fps:.2f}s")
                timestamp = frame_count / self.fps
                logger.debug(f"Processing frame at {timestamp:.2f}s")

                img_base64 = self.frame_to_base64(frame)

                context = f"""Describe this frame from a video. Focus on the main elements, actions, and any notable details. Here is the transcript around the time of the frame:
                ---
                {self.transcript.at_time(timestamp, padding=10)}
                ---

                Here is a description of the previous frame:
                ---
                {last_description if last_description else 'No previous frame description available, this is the first frame'}
                ---

                In your response, only provide the description of the current frame, using the above information as context.
                """

                last_description = await self.vision_client.get_frame_description(img_base64, context)
                time_to_description[timestamp] = last_description

            frame_count += 1

        logger.info(f"Generated descriptions for {len(time_to_description)} frames")
        return TimeSeriesData(time_to_content=time_to_description)

    async def process_video(self) -> ParseVideoResult:
        """
        Process the video to get both transcript and frame descriptions

        Returns:
            Dictionary containing transcript and frame descriptions as TimeSeriesData objects
        """
        logger.info("Starting full video processing")
        metadata = {
            "duration": self.duration,
            "fps": self.fps,
            "total_frames": self.total_frames,
            "frame_sample_rate": self.frame_sample_rate,
        }
        result = ParseVideoResult(
            metadata=metadata,
            transcript=self.get_transcript(),
            frame_descriptions=await self.get_frame_descriptions(),
        )
        logger.info("Video processing completed successfully")
        return result

    def __del__(self):
        """Clean up video capture object"""
        if hasattr(self, "cap"):
            logger.debug("Releasing video capture resources")
            self.cap.release()
