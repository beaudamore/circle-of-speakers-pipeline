"""
title: Dynamic Circle
author: beaudamore
date: 2025-09-15
version: 3.0
license: MIT
description: Dynamic Circle of Speakers - all speakers, AI-selected and ordered (inherits from Circle Blueprint)
"""

from typing import Optional
from pydantic import Field
import sys

# Import the Circle of Speakers blueprint (mounted at /app/blueprints in Docker)
sys.path.insert(0, '/app/blueprints')
from circle_of_speakers_blueprint import Pipeline as CircleBlueprint


class Pipeline(CircleBlueprint):
    """
    Dynamic Circle - Includes ALL speakers, AI selects and orders the most relevant ones.
    
    This is the default circle with no tag filtering.
    The orchestration AI picks from every available speaker.
    """

    class Valves(CircleBlueprint.Valves):
        # ==============================================================
        # BASE API SETTINGS (inherited from StreamingBlueprint)
        # ==============================================================
        OPENWEBUI_ENDPOINT: str = "http://host.docker.internal:3000"
        OPENWEBUI_API_KEY: str = Field(default="", description="Must use JWT token")
        USER_AGENT: str = Field(
            default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            description="User-Agent header to use for all API requests to OpenWebUI.",
        )
        enable_full_debug: bool = Field(default=False, description="Enable heavy debugging logs, including payloads/results (masked & truncated).")
        enable_step_debug: bool = Field(default=False, description="Enable step-by-step progress logs (concise, truncated).")

        # ==============================================================
        # SPEAKER SELECTION — the primary differentiator per circle
        # ==============================================================
        SPEAKER_TAGS: Optional[str] = Field(
            default="",
            description="Leave empty for dynamic AI selection from all speakers. "
                        "Or filter with comma-separated tags (e.g., 'stoic,biblical'). "
                        "Use '+' for AND (e.g., 'stoic+greek').",
        )

        # ==============================================================
        # ORCHESTRATION
        # ==============================================================
        ORCHESTRATION_MODEL_NAME: str = Field(
            default="Intelligent Speaker Ordering",
            description="Model name to use for intelligent speaker orchestration. "
                        "The system prompt from this model will be used as the orchestration prompt template.",
        )
        DECISION_CONTEXT_DEPTH: int = Field(
            default=4,
            description="Number of previous messages to include for ordering decisions (0=none, 4-6=recent, 8-10=extended).",
        )

        # ==============================================================
        # DYNAMIC INTRODUCTIONS
        # ==============================================================
        ENABLE_DYNAMIC_INTRODUCTIONS: bool = Field(
            default=True,
            description="Enable automatic speaker introductions when they first appear in a conversation",
        )

        # ==============================================================
        # USER PROFILE INTEGRATION
        # ==============================================================
        ENABLE_USER_PROFILE_INTEGRATION: bool = Field(
            default=True,
            description="Extract and use personal information from user's system prompt to personalize speaker responses",
        )

        # ==============================================================
        # PROFILE IMAGES
        # ==============================================================
        PROFILE_THUMBNAIL_ROOT: str = Field(
            default="/api/v1/models/model/profile/image?id={model_id}&width={size}",
            description="Avatar URL template with {model_id} and {size} placeholders (default: Open WebUI's own "
                        "model-image endpoint). No placeholders = prefix form {root}{model_id}?width={size} for an "
                        "external resizer. Empty = names only.",
        )
        PROFILE_IMAGE_SIZE: int = Field(
            default=60,
            description="Requested avatar width in pixels (fills {size}).",
        )

        # ==============================================================
        # PROMPT PREFIXES
        # ==============================================================
        FIRST_SPEAKER_PROMPT_PREFIX: str = Field(
            default=(
                "📢 **YOU ARE THE FIRST SPEAKER:** You're opening this round of discussion, "
                "so focus on giving the user a helpful, engaging response that reflects your "
                "personality, background, and natural way of speaking as {speaker_name}."
            ),
            description="Prefix prepended to the System Prompt for the first speaker.",
            json_schema_extra={"widget": "textarea", "rows": 3},
        )
        INTRODUCTION_PROMPT_PREFIX: str = Field(
            default=(
                "🎭 **FIRST TIME IN THIS CONVERSATION:** This is your first time participating "
                "in this specific conversation. Before responding to the user's question, briefly "
                "introduce yourself by name and mention your area of expertise or perspective. "
                "Keep it concise (1-2 sentences), then proceed with your response."
            ),
            description="Prefix prepended to the System Prompt when a speaker appears for the first time.",
            json_schema_extra={"widget": "textarea", "rows": 3},
        )

    def __init__(self):
        super().__init__()
        self.name = "Dynamic Circle"
