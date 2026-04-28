"""
title: Circle of Speakers Blueprint
author: beaudamore
date: 2025-09-15
version: 2.0
license: MIT
description: Full Circle of Speakers blueprint - provides multi-speaker orchestration, streaming responses, conversation awareness, and all circle logic. Inherit from this to create themed circle variants by simply overriding valve defaults.
"""

from typing import List, Dict, Optional
import json
import re
import gc
from datetime import datetime
from pydantic import Field
import requests

# Import the base streaming blueprint (co-located in /app/blueprints)
from openwebui_streaming_blueprint import Pipeline as StreamingBlueprint


class Pipeline(StreamingBlueprint):
    """
    Circle of Speakers Blueprint - Full multi-speaker pipeline logic.
    
    Inherits API/streaming/debug from StreamingBlueprint.
    
    To create a new circle variant, inherit from this class and override
    valve defaults (especially SPEAKER_TAGS) in a thin ~30-line pipeline file.
    """

    class Valves(StreamingBlueprint.Valves):
        """Full Circle of Speakers configuration - inherits base API settings from StreamingBlueprint"""

        # ======================================================================
        # SPEAKER SELECTION - This is the PRIMARY valve for variant pipelines
        # Override SPEAKER_TAGS default to create themed circles
        # ======================================================================
        SPEAKER_TAGS: Optional[str] = Field(
            default="",
            description="Comma-separated list of tags to select which speakers to load. "
                        "Use ',' for OR (e.g., stoic,biblical) and '+' for AND (e.g., stoic+greek). "
                        "Leave empty to select from all speakers.",
        )

        # ======================================================================
        # ORCHESTRATION - AI-driven speaker selection and ordering
        # ======================================================================
        ORCHESTRATION_MODEL_NAME: str = Field(
            default="Intelligent Speaker Ordering",
            description="Model name to use for intelligent speaker orchestration. "
                        "The system prompt from this model will be used as the orchestration prompt template. "
                        "Use {user_message}, {conversation_context}, and {speaker_expertise} as placeholders. "
                        "{speaker_expertise} contains each speaker's name, description (expertise), and tags in markdown format.",
        )

        DECISION_CONTEXT_DEPTH: int = Field(
            default=4,
            description="Number of previous rounds of messages to include for ordering decisions "
                        "(0=no context, 2=last round, 4-6=recent history, 8-10=extended context for many speakers). "
                        "Higher values use more tokens.",
        )

        # ======================================================================
        # DYNAMIC INTRODUCTIONS
        # ======================================================================
        ENABLE_DYNAMIC_INTRODUCTIONS: bool = Field(
            default=True,
            description="Enable automatic speaker introductions when they first appear in a conversation",
        )

        # ======================================================================
        # USER PROFILE INTEGRATION
        # ======================================================================
        ENABLE_USER_PROFILE_INTEGRATION: bool = Field(
            default=True,
            description="Extract and use personal information from user's system prompt to personalize speaker responses",
        )

        # ======================================================================
        # PROFILE IMAGE CONFIGURATION
        # ======================================================================
        PROFILE_THUMBNAIL_ROOT: str = Field(
            default="https://images.crossandfaith.com/image/",
            description="Base URL for speaker profile images. Images will be accessed as {root_url}{model_id}.png",
        )
        PROFILE_IMAGE_SIZE: int = Field(
            default=60,
            description="Profile image size in pixels (square dimensions, e.g., 60 = 60x60px)",
        )

        # ======================================================================
        # PROMPT PREFIXES - Customize speaker behavior
        # ======================================================================
        FIRST_SPEAKER_PROMPT_PREFIX: str = Field(
            default=(
                "📢 **YOU ARE THE FIRST SPEAKER:** You're opening this round of discussion, "
                "so focus on giving the user a helpful, engaging response that reflects your "
                "personality, background, and natural way of speaking as {speaker_name}."
            ),
            description="Terse prefix prepended to the pipeline System Prompt for the first speaker. "
                        "This gets added before the main awareness prompt.",
            json_schema_extra={"widget": "textarea", "rows": 3},
        )

        INTRODUCTION_PROMPT_PREFIX: str = Field(
            default=(
                "🎭 **FIRST TIME IN THIS CONVERSATION:** This is your first time participating "
                "in this specific conversation. Before responding to the user's question, briefly "
                "introduce yourself by name and mention your area of expertise or perspective. "
                "Keep it concise (1-2 sentences), then proceed with your response."
            ),
            description="Terse prefix prepended to the pipeline System Prompt when a speaker appears "
                        "for the first time. This gets added before the main awareness prompt.",
            json_schema_extra={"widget": "textarea", "rows": 3},
        )

    # =====================================================================
    # INITIALIZATION
    # =====================================================================

    def __init__(self):
        super().__init__()  # Initialize StreamingBlueprint (debug helpers, API methods, available_models)
        self.name = "Circle of Speakers (Blueprint)"
        self.valves = self.Valves()
        self.all_speakers: List[dict] = []                    # In-memory list of all possible speakers
        self.conversation_participants: Dict[str, set] = {}   # Tracks all unique speakers per conversation
        self.introduced_speakers: Dict[str, set] = {}         # Tracks which speakers have introduced themselves per conversation
        self._update_tags_description()

    # =====================================================================
    # LIFECYCLE HOOKS
    # =====================================================================

    async def on_startup(self):
        """Called when the pipeline starts up"""
        self._dbg_step(f"🎭 Starting {self.name}")
        try:
            self._initialize_speakers()
        except (ValueError, Exception) as e:
            print(f"⚠️ {self.name}: Deferred speaker initialization (valves not yet loaded): {e}")
        self._update_tags_description()

    async def on_shutdown(self):
        """Called when the pipeline shuts down to clean up resources."""
        self._dbg_step(f"🛑 Shutting down {self.name}")
        self.all_speakers.clear()
        self.introduced_speakers.clear()
        self.conversation_participants.clear()
        self._dbg_step(f"✅ {self.name} shutdown complete.")

    async def on_valves_updated(self):
        """Called when valve settings are updated"""
        self._dbg_step("⚙️ Pipeline valves updated")
        self._initialize_speakers()
        self._update_tags_description()

    # =====================================================================
    # MAIN PIPELINE
    # =====================================================================

    def pipe(self, user_message: str, messages: List[dict], body: dict, **kwargs):
        """Main pipeline with streaming and real-time conversation awareness"""

        # Truncate history early to stay within model context limits
        messages = self._truncate_history(messages)

        # Check if usage tracking is requested (from Open WebUI checkbox)
        include_usage = body.get("stream_options", {}).get("include_usage", False)
        self._dbg_step(f"📊 Usage tracking: {'enabled' if include_usage else 'disabled'}")

        # Use cached speakers (loaded on startup / valves update)
        # Only fetch from API if cache is empty (first run or after shutdown)
        if not self.all_speakers:
            self._dbg_step("🔄 Speaker cache empty — fetching from API...")
            self._initialize_speakers()

        # Extract web search context if present (inject into shared awareness)
        web_search_context = self._extract_web_search_context(messages)
        if web_search_context:
            yield "🔍 **Web search data detected - enhancing speaker responses**\n\n"

        # Extract memory context if present (inject into shared awareness)
        memory_context = self._extract_memory_context(messages)

        awareness_prompt_template = self._extract_pipeline_system_prompt(body)
        if not awareness_prompt_template:
            yield (
                "❌ PIPELINE STOPPED: The pipeline's System Prompt is empty. "
                "Please provide the awareness instructions in the Dynamic Circle system prompt field."
            )
            self._dbg_step("❌ Missing pipeline system prompt — aborting run.")
            return

        # Append web search and memory to awareness template (more efficient than per-speaker injection)
        if web_search_context:
            awareness_prompt_template += f"\n\n{web_search_context}"
        if memory_context:
            awareness_prompt_template += f"\n\n{memory_context}"

        # --- 1. UNIFIED ORCHESTRATION ---
        if not self.all_speakers:
            yield "❌ PIPELINE STOPPED: Cannot fetch models from OpenWebUI and speaker list is empty."
            return

        initial_speakers = self._get_active_speakers()
        if not initial_speakers:
            yield "❌ No speakers configured."
            return

        # Show status BEFORE the slow orchestrator AI call so the user sees progress
        yield {
            "event": {
                "type": "status",
                "data": {
                    "description": f"Found {len(initial_speakers)} speakers. Selecting order...",
                    "done": False,
                },
            }
        }

        # Get recent conversation context for better ordering decisions
        conv_key = self._get_conversation_key(body)
        recent_context = self._get_recent_conversation_context(messages)

        # Perform AI-driven selection and ordering
        tag_query = str(self.valves.SPEAKER_TAGS or "").strip()
        active_speakers = self._analyze_user_message_for_speaker_order(
            user_message, initial_speakers, recent_context, tag_query, memory_context
        )
        final_order = [speaker["name"] for speaker in active_speakers]

        yield {
            "event": {
                "type": "status",
                "data": {
                    "description": f"**AI Speaker Order:** {' → '.join(final_order)}",
                    "done": True,
                },
            }
        }

        # Visual feedback showing selected speakers
        speaker_count = len(active_speakers)
        speaker_list = ", ".join([s["name"] for s in active_speakers])
        yield f"💬 **{speaker_count} speaker{'s' if speaker_count != 1 else ''} selected:** {speaker_list}\n\n"

        # --- 2. MAIN RESPONSE LOOP ---
        # Initialize introduced speakers set for this conversation if needed
        if conv_key not in self.introduced_speakers:
            self.introduced_speakers[conv_key] = set()

        speaker_responses = []
        current_round_speakers_list = active_speakers

        # Track aggregated usage across all speakers (only if usage tracking enabled)
        total_usage = None
        if include_usage:
            total_usage = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }

        # Historical Awareness Logic
        if conv_key not in self.conversation_participants:
            self.conversation_participants[conv_key] = set()
        current_round_speaker_names = {s["name"] for s in current_round_speakers_list}
        self.conversation_participants[conv_key].update(current_round_speaker_names)

        # Historical speakers are anyone who has ever participated, minus the current speakers
        historical_speaker_names = (
            self.conversation_participants[conv_key] - current_round_speaker_names
        )

        def get_speaker_details(speaker_name):
            for speaker in self.all_speakers:
                if speaker["name"] == speaker_name:
                    description = speaker.get("description", "No description available.")
                    tags_set = speaker.get("tags", set())
                    tags = ", ".join(sorted(list(tags_set))) if tags_set else ""
                    return f"- {speaker_name} (Description: {description}, Tags: {tags})"
            return f"- {speaker_name}"

        current_speakers_str = (
            "\n".join(
                [get_speaker_details(name) for name in sorted(list(current_round_speaker_names))]
            )
            if current_round_speaker_names
            else "None"
        )
        historical_speakers_str = (
            "\n".join(
                [get_speaker_details(name) for name in sorted(list(historical_speaker_names))]
            )
            if historical_speaker_names
            else "None"
        )

        current_round_responded_speakers = []
        user_profile = (
            self._extract_user_profile(messages)
            if self.valves.ENABLE_USER_PROFILE_INTEGRATION
            else {"personal_info": "", "system_instructions": ""}
        )

        for i, speaker in enumerate(active_speakers):
            try:
                # Check if this speaker has already introduced themselves in this conversation
                speaker_name = speaker["name"]
                needs_introduction = (
                    self.valves.ENABLE_DYNAMIC_INTRODUCTIONS
                    and speaker_name not in self.introduced_speakers[conv_key]
                )

                # Build context for each speaker (first vs. subsequent)
                if i > 0:
                    previous_takes = [
                        f"• {current_round_responded_speakers[j]['name']} said: {res[:200]}{'...' if len(res) > 200 else ''}"
                        for j, res in enumerate(speaker_responses)
                    ]
                    awareness_context = "\n".join(previous_takes)

                    # Build base prompt from pipeline system prompt
                    base_prompt = awareness_prompt_template

                    # Prepend introduction prefix if this is their first time
                    if needs_introduction:
                        intro_prefix = str(self.valves.INTRODUCTION_PROMPT_PREFIX).format(
                            speaker_name=speaker_name
                        )
                        prompt_template = intro_prefix + base_prompt
                    else:
                        prompt_template = base_prompt

                    # Format the complete prompt (escape user content to prevent format string issues with vLLM)
                    system_prompt_content = prompt_template.format(
                        speaker_name=self._escape_format_braces(speaker_name),
                        user_message=self._escape_format_braces(user_message),
                        previous_context=self._escape_format_braces(awareness_context),
                        current_date=datetime.now().strftime("%B %d, %Y"),
                        current_round_speakers=self._escape_format_braces(current_speakers_str),
                        historical_speakers=self._escape_format_braces(historical_speakers_str),
                        introduction_instructions="",
                    )
                else:  # First speaker
                    # Build base prompt from pipeline system prompt
                    base_prompt = awareness_prompt_template

                    # Prepend appropriate prefix based on introduction status
                    if needs_introduction:
                        intro_prefix = str(self.valves.INTRODUCTION_PROMPT_PREFIX).format(
                            speaker_name=speaker_name
                        )
                        prompt_template = intro_prefix + base_prompt
                    else:
                        first_speaker_prefix = str(self.valves.FIRST_SPEAKER_PROMPT_PREFIX).format(
                            speaker_name=speaker_name
                        )
                        prompt_template = first_speaker_prefix + base_prompt

                    # Format the complete prompt (escape user content to prevent format string issues with vLLM)
                    system_prompt_content = prompt_template.format(
                        speaker_name=self._escape_format_braces(speaker_name),
                        user_message=self._escape_format_braces(user_message),
                        previous_context="",  # No previous context for first speaker
                        current_date=datetime.now().strftime("%B %d, %Y"),
                        current_round_speakers=self._escape_format_braces(current_speakers_str),
                        historical_speakers=self._escape_format_braces(historical_speakers_str),
                        introduction_instructions="",
                    )

                # Mark this speaker as introduced
                if needs_introduction:
                    self.introduced_speakers[conv_key].add(speaker_name)

                # Build complete speaker prompt with user context
                user_context = self._build_user_context_section(user_profile)
                full_system_prompt = system_prompt_content + user_context

                speaker_messages = [
                    {"role": "system", "content": full_system_prompt},
                    {"role": "user", "content": user_message},
                ]

                # Get tool IDs for this speaker's model
                speaker_tool_ids = self._get_model_tool_ids(speaker["model"])

                # Inline feedback if tools are configured
                if speaker_tool_ids:
                    tool_names = [tool_id.replace('_', ' ').title() for tool_id in speaker_tool_ids]
                    tools_list = ", ".join(tool_names)
                    yield f"🔧 **{speaker['name']} using tools:** {tools_list}\n\n"

                # UI events and streaming response
                yield {
                    "event": {
                        "type": "tool",
                        "data": {
                            "tool": f"{speaker['name']} Generator",
                            "status": "running",
                            "description": f"{speaker['name']} is thinking...",
                        },
                    }
                }

                # Generate speaker image markdown
                yield self.get_speaker_image_markdown(speaker)

                # Stream and automatically detect thinking (from API fields or XML tags)
                reasoning_active = False
                speaker_usage = None

                full_response = ""
                for chunk in self._query_openwebui_model_streaming(
                    speaker["model"], speaker_messages, tool_ids=speaker_tool_ids, include_usage=include_usage
                ):
                    if chunk and not chunk.startswith("❌"):
                        # Check for usage data marker from blueprint
                        if chunk.startswith("__USAGE_DATA__:"):
                            try:
                                usage_json = chunk[len("__USAGE_DATA__:"):]
                                speaker_usage = json.loads(usage_json)
                                self._dbg_step(f"  📊 {speaker['name']} usage: {speaker_usage}")
                            except json.JSONDecodeError:
                                self._dbg_step(f"  ⚠️ Failed to parse usage data: {chunk}")
                            continue

                        # Check for API reasoning marker (o1, thinking models)
                        if chunk.startswith("__REASONING_CHUNK__:"):
                            reasoning_chunk = chunk[len("__REASONING_CHUNK__:"):]

                            # Open details tag on first reasoning chunk
                            if not reasoning_active:
                                yield f"<details>\n<summary>💭 {speaker['name']}'s Thinking</summary>\n\n"
                                reasoning_active = True

                            # Stream reasoning chunk immediately
                            yield reasoning_chunk
                            continue

                        # Check for XML thinking tags in content (Qwen, DeepSeek, etc.)
                        if chunk.startswith("__THINKING_TAG_CONTENT__:"):
                            tag_content = chunk[len("__THINKING_TAG_CONTENT__:"):]

                            # Open details tag on first thinking chunk
                            if not reasoning_active:
                                yield f"<details>\n<summary>💭 {speaker['name']}'s Thinking</summary>\n\n"
                                reasoning_active = True

                            # Strip any residual XML tags and stream directly
                            cleaned = re.sub(r'</?think>|</?thinking>', '', tag_content)
                            if cleaned:
                                yield cleaned
                            continue

                        # Check for thinking tag close marker from blueprint
                        if chunk == "__THINKING_TAG_CLOSE__":
                            if reasoning_active:
                                yield "\n\n</details>\n\n"
                                reasoning_active = False
                            continue

                        # If we were streaming reasoning and now have regular content, close the details tag
                        if reasoning_active and chunk:
                            yield "\n\n</details>\n\n"
                            reasoning_active = False

                        # Safety: strip any residual think tags that slipped through
                        cleaned_chunk = re.sub(r'</?think>|</?thinking>', '', chunk)
                        if cleaned_chunk:
                            yield cleaned_chunk
                            full_response += cleaned_chunk

                # If reasoning was the last thing (edge case), close the details tag
                if reasoning_active:
                    yield "\n\n</details>\n\n"

                # Aggregate usage data from this speaker (only if tracking enabled)
                if include_usage and speaker_usage and total_usage is not None:
                    total_usage["prompt_tokens"] += speaker_usage.get("prompt_tokens", 0)
                    total_usage["completion_tokens"] += speaker_usage.get("completion_tokens", 0)
                    total_usage["total_tokens"] += speaker_usage.get("total_tokens", 0)

                # Yield citation events if tools were configured for this speaker
                if speaker_tool_ids:
                    for citation_event in self._generate_tool_citations(speaker_tool_ids, speaker["name"], full_response):
                        yield citation_event

                speaker_responses.append(full_response.strip())
                current_round_responded_speakers.append(speaker)

                yield "\n\n---\n\n"
                if i < len(active_speakers) - 1:
                    yield {
                        "event": {
                            "type": "tool",
                            "data": {
                                "tool": f"{active_speakers[i+1]['name']} Generator",
                                "status": "running",
                                "description": f"{active_speakers[i+1]['name']} is speaking...",
                            },
                        }
                    }

            except (ValueError, TypeError, KeyError) as e:
                yield f"❌ **{speaker['name']} Error**: {str(e)}\n\n"
                speaker_responses.append(f"Error: {str(e)}")
                current_round_responded_speakers.append(speaker)

        yield "✅ **Circle Complete** - All speakers have responded\n\n"

        yield {"event": {"type": "status", "data": {"description": "", "done": True}}}

        # Yield aggregated usage data if tracking was enabled and data was collected
        if include_usage and total_usage and total_usage.get("total_tokens", 0) > 0:
            self._dbg_step(f"📊 Total usage across all speakers: {total_usage}")
            yield {
                "usage": {
                    "prompt_tokens": total_usage["prompt_tokens"],
                    "completion_tokens": total_usage["completion_tokens"],
                    "total_tokens": total_usage["total_tokens"],
                }
            }

        gc.collect()

    # =====================================================================
    # SPEAKER MANAGEMENT
    # =====================================================================

    def _escape_format_braces(self, text: str) -> str:
        """
        Escape curly braces in user-provided content to prevent format string injection.
        This is critical for vLLM compatibility - unescaped braces cause parsing errors.
        """
        if not isinstance(text, str):
            return str(text) if text else ""
        return text.replace("{", "{{").replace("}", "}}")

    def _initialize_speakers(self):
        """
        Initializes the in-memory speaker list by fetching all models directly
        from the OpenWebUI API. This is the SINGLE SOURCE OF TRUTH for speaker data.
        All tag processing happens here, once.
        """
        self._dbg_step("--- Speaker Initialization (In-Memory) ---")
        self.all_speakers = []  # CRITICAL: Clear previous list

        all_api_models = self._fetch_available_models_sync()
        self._dbg_step(f"  Fetched {len(all_api_models)} total models from OpenWebUI API.")

        api_models = [
            model
            for model in all_api_models
            if (model.get("meta", {}).get("description") or "").strip()
            and (
                (model.get("meta", {}).get("tags", []) or [])
                not in ["default", "system", ""]
            )
        ]
        self._dbg_step(
            f"  Filtered to {len(api_models)} models with description and >1 valid tag."
        )

        if not api_models:
            self._dbg_step("  Result: CRITICAL - Failed to fetch models from OpenWebUI API. No speakers will be available.")
            self._dbg_step("------------------------------------------\n")
            return

        self._dbg_step(f"  Processing {len(api_models)} models from API response...")

        in_memory_speakers = []
        for model in api_models:
            model_id = model.get("id")
            model_name = model.get("name")

            if not model_id or not model_name:
                self._dbg_step("    ⚠️ SKIPPED: Model missing 'id' or 'name'.")
                continue

            # This is the ONLY place where tags are processed
            meta = model.get("meta", {})
            raw_tags = meta.get("tags", []) if isinstance(meta, dict) else []

            # Filter tags: ignore 'system' tag and ensure tag is valid
            tags_set = {
                tag["name"].lower()
                for tag in raw_tags
                if isinstance(tag, dict)
                and tag.get("name")
                and tag["name"].lower() != "system"
            }

            description = meta.get("description", "") if isinstance(meta, dict) else ""

            in_memory_speakers.append(
                {
                    "name": model_name,
                    "model": model_id,
                    "enabled": model.get("is_active", True),
                    "tags": tags_set,
                    "description": description,
                }
            )
            self._dbg_step(
                f"    ✅ LOADED: Speaker '{model_name}' (ID: '{model_id}') with tags: {tags_set if tags_set else 'None'}"
            )

        self.all_speakers = in_memory_speakers
        self._dbg_step(
            f"  Result: OK - Loaded {len(self.all_speakers)} speakers directly from API into memory."
        )
        self._dbg_step("------------------------------------------\n")

    def _update_tags_description(self):
        """Updates the UI description for the SPEAKER_TAGS valve with all available tags and syntax guide."""
        if not self.all_speakers:
            available_tags_str = "No speakers loaded."
        else:
            all_tags = set()
            for speaker in self.all_speakers:
                all_tags.update(speaker.get("tags", set()))

            if all_tags:
                available_tags_str = "Available tags: " + ", ".join(sorted(list(all_tags)))
            else:
                available_tags_str = "No tags defined on models."

        syntax_guide = "Use ',' for OR (e.g., tag1,tag2) and '+' for AND (e.g., tag1+tag2)."
        self._dbg_step(
            f"SPEAKER_TAGS Description Hint: Filter speakers by tags. {syntax_guide} {available_tags_str}"
        )

    def get_speaker_image_markdown(self, speaker: dict, greeting: bool = False) -> str:
        """Generate consistent speaker image markdown with optional microphone emoji for greeting."""
        emoji = "🎤 " if greeting else ""
        thumbnail_root = getattr(self.valves, "PROFILE_THUMBNAIL_ROOT", None)
        size = getattr(self.valves, "PROFILE_IMAGE_SIZE", 60)

        if thumbnail_root and thumbnail_root.strip():
            profile_image_url = f"{thumbnail_root}{speaker['model']}?width={size}"
            return f'![{speaker["name"]}]({profile_image_url}) **{speaker["name"]}**:\n'
        else:
            return f"**{emoji}{speaker['name']}:**\n"

    def _get_active_speakers(self) -> List[dict]:
        """
        Get all enabled speakers from the in-memory list that match the tag query.
        If no speakers match the query, raises ValueError to fail fast.
        """
        active_speakers = []
        tag_query = str(self.valves.SPEAKER_TAGS or "").strip()

        if not self.all_speakers:
            self._dbg_step("⚠️ Speaker list is empty. Cannot get active speakers.")
            return []

        # Split the query into OR groups, ignoring empty strings from trailing commas
        or_groups = [
            group.strip() for group in tag_query.lower().split(",") if group.strip()
        ]
        self._dbg_step(f"  Tag Query: '{tag_query}' -> OR Groups: {or_groups}")

        # --- Primary Search ---
        if tag_query:
            self._dbg_step("  Performing primary search based on tags...")
            for speaker_config in self.all_speakers:
                if speaker_config.get("enabled"):
                    speaker_tags = speaker_config.get("tags", set())
                    self._dbg_step(
                        f"    Checking Speaker: '{speaker_config['name']}' with tags: {speaker_tags}"
                    )

                    for group in or_groups:
                        and_tags = {
                            tag.strip() for tag in group.split("+") if tag.strip()
                        }
                        self._dbg_step(f"      Matching against AND group: {and_tags}")
                        if and_tags.issubset(speaker_tags):
                            self._dbg_step(
                                f"        ✅ MATCH FOUND. Adding '{speaker_config['name']}' to active list."
                            )
                            active_speakers.append(
                                {
                                    "name": speaker_config["name"],
                                    "model": speaker_config["model"],
                                    "description": speaker_config.get("description", ""),
                                    "tags": speaker_config.get("tags", set()),
                                }
                            )
                            break  # Move to next speaker once a match is found
        else:
            # If no tags are provided, get all enabled speakers
            self._dbg_step("  No tag query provided. Getting all enabled speakers for AI selection.")
            for speaker_config in self.all_speakers:
                if speaker_config.get("enabled"):
                    self._dbg_step(f"    Adding enabled speaker: '{speaker_config['name']}'")
                    active_speakers.append(
                        {
                            "name": speaker_config["name"],
                            "model": speaker_config["model"],
                            "description": speaker_config.get("description", ""),
                            "tags": speaker_config.get("tags", set()),
                        }
                    )

        # Fail fast if no speakers match
        if not active_speakers and tag_query:
            raise ValueError(
                f"No speakers found matching tag query: '{tag_query}'. "
                f"Available speakers: {[s['name'] for s in self.all_speakers]}"
            )

        # Remove duplicates
        unique_speakers = []
        seen_names = set()
        for speaker in active_speakers:
            if speaker["name"] not in seen_names:
                unique_speakers.append(speaker)
                seen_names.add(speaker["name"])

        self._dbg_step(f"  Final speaker count: {len(unique_speakers)}")
        return unique_speakers

    # =====================================================================
    # CONVERSATION CONTEXT & ORCHESTRATION
    # =====================================================================

    def _get_conversation_key(self, body: dict) -> str:
        """Generate a unique key for conversation memory"""
        return body.get("chat_id", body.get("session_id", "default"))

    def _get_recent_conversation_context(self, messages: List[dict]) -> str:
        """Extract recent context from OpenWebUI's message history"""
        recent_context = ""
        if self.valves.DECISION_CONTEXT_DEPTH <= 0 or not messages:
            return ""

        context_depth = min(self.valves.DECISION_CONTEXT_DEPTH, len(messages))

        if context_depth > 0:
            recent_messages = messages[-context_depth:]
            context_parts = []

            for msg in recent_messages:
                role = msg.get("role", "")
                content = msg.get("content", "")

                max_content_length = max(50, 200 - (context_depth * 15))
                content_truncated = content[:max_content_length]
                if len(content) > max_content_length:
                    content_truncated += "..."

                if role == "user":
                    context_parts.append(f"User: {content_truncated}")
                elif role == "assistant":
                    if ": " in content_truncated:
                        speaker_name, speaker_response = content_truncated.split(": ", 1)
                        context_parts.append(f"{speaker_name}: {speaker_response}")
                    else:
                        context_parts.append(f"Speaker: {content_truncated}")

            recent_context = "\n".join(context_parts)
        return recent_context

    def _get_orchestration_prompt_template(self) -> str:
        """
        Fetch the system prompt from the orchestration model to use as the prompt template.
        Returns the system prompt or raises if not found.
        """
        try:
            ordering_model_id = self._resolve_model_id(self.valves.ORCHESTRATION_MODEL_NAME)

            for model in self.available_models:
                if model.get("id") == ordering_model_id or model.get("name") == self.valves.ORCHESTRATION_MODEL_NAME:
                    params = model.get("params", {})
                    if not isinstance(params, dict):
                        raise ValueError(
                            f"Orchestration model '{self.valves.ORCHESTRATION_MODEL_NAME}' has invalid structure - "
                            f"'params' is not a dict: {type(params)}"
                        )

                    system_prompt = params.get("system", "")

                    if system_prompt:
                        self._dbg_step(f"✅ Extracted system prompt from orchestration model '{self.valves.ORCHESTRATION_MODEL_NAME}'")
                        self._dbg_step(f"   Prompt length: {len(system_prompt)} characters")
                        return system_prompt
                    else:
                        if self._is_full_debug():
                            raise ValueError(
                                f"Orchestration model '{self.valves.ORCHESTRATION_MODEL_NAME}' has no system prompt in params.system. "
                                f"Model structure: {json.dumps(model, indent=2)}"
                            )
                        else:
                            model_name = model.get('name', 'unknown')
                            model_id = model.get('id', 'unknown')
                            raise ValueError(
                                f"Orchestration model '{self.valves.ORCHESTRATION_MODEL_NAME}' has no system prompt in params.system "
                                f"(model name='{model_name}', id='{model_id}'). Enable Full Debug to dump full model."
                            )

            raise ValueError(
                f"Orchestration model '{self.valves.ORCHESTRATION_MODEL_NAME}' not found in available models. "
                f"Available models: {[m.get('name') for m in self.available_models]}"
            )

        except ValueError:
            raise
        except Exception as e:
            raise RuntimeError(
                f"Unexpected error fetching orchestration prompt from model '{self.valves.ORCHESTRATION_MODEL_NAME}': {e}"
            ) from e

    def _analyze_user_message_for_speaker_order(
        self,
        user_message: str,
        active_speakers: List[dict],
        conversation_context: str = "",
        tag_query: str = "",
        memory_context: str = "",
    ) -> List[dict]:
        """
        Analyze user message using AI to determine optimal speaker order.
        If tag_query is empty, performs SELECTION and ORDERING from all speakers.
        If tag_query has value, performs ORDERING on the pre-filtered speakers.
        """
        try:
            # Build context about available speakers with their expertise/personalities
            speaker_descriptions = []
            for speaker in active_speakers:
                description = speaker.get("description", "No description available.")
                tags = (
                    ", ".join(speaker.get("tags", []))
                    if isinstance(speaker.get("tags"), set)
                    else ""
                )
                speaker_descriptions.append(
                    f"## speaker\n## name: {speaker['name']}\n## description: {description}\n## tags: {tags}"
                )

            speakers_context = "\n".join(speaker_descriptions)

            # Add conversation context if available
            if conversation_context.strip():
                context_section = (
                    f"PREVIOUS CONVERSATION CONTEXT:\n"
                    f"{conversation_context[:500]}{'...' if len(conversation_context) > 500 else ''}"
                )
            else:
                context_section = ""

            # Add memory context if available
            if memory_context.strip():
                context_section += f"\n{memory_context}"

            # Build the dynamic content to send as user message
            dynamic_content = f"""**AVAILABLE CAST:**
{speakers_context}

**RECENT CONVERSATION:**
{context_section if context_section.strip() else "No previous context."}

**USER'S MESSAGE:**
"{user_message}"

Select and order the speakers now."""

            self._dbg_step("--- Orchestration Analysis ---")
            self._dbg_step(f"  Mode: {'SELECTION & ORDERING' if not tag_query else 'ORDERING'}")
            self._dbg_step(f"  User Message: {user_message}")
            self._dbg_step(f"  Dynamic Content Length: {len(dynamic_content)} chars")
            self._dbg_step("-----------------------------")

            ordering_messages = [
                {"role": "user", "content": dynamic_content},
            ]

            self._dbg_step(f"  Orchestration messages: {len(ordering_messages)} messages")

            ordering_model_id = self._resolve_model_id(self.valves.ORCHESTRATION_MODEL_NAME)

            # Get AI analysis
            response = ""
            for chunk in self._query_openwebui_model_streaming(ordering_model_id, ordering_messages):
                if chunk and not chunk.startswith("❌"):
                    response += chunk

            # Parse markdown response to get ordered speaker names
            if response.strip():
                lines = response.strip().split("\n")
                ordered_names = []

                for line in lines:
                    line = line.strip()
                    if line.startswith("#####"):
                        speaker_name = line.replace("#####", "").strip()
                        if speaker_name:
                            ordered_names.append(speaker_name)
                self._dbg_step(f"  AI Ordered Names: {ordered_names}")

                # Reorder speakers based on AI recommendation
                ordered_speakers = []

                for name in ordered_names:
                    name_lower = name.lower().strip()
                    for speaker in active_speakers:
                        speaker_name_lower = speaker["name"].lower().strip()

                        # Multiple matching strategies for flexibility
                        if (
                            speaker_name_lower == name_lower
                            or name_lower in speaker_name_lower
                            or speaker_name_lower in name_lower
                            or speaker_name_lower.split(",")[0].strip() == name_lower
                            or speaker_name_lower.split()[0] == name_lower
                        ):
                            ordered_speakers.append(speaker)
                            self._dbg_step(f"  ✅ Matched '{name}' to speaker '{speaker['name']}'")
                            break

                return ordered_speakers
            else:
                raise ValueError(
                    f"Orchestration model '{self.valves.ORCHESTRATION_MODEL_NAME}' returned empty response. "
                    f"The model may not be working properly or its system prompt may be incorrect."
                )

        except (requests.exceptions.RequestException, json.JSONDecodeError, ValueError) as e:
            self._dbg_step(f"❌ CRITICAL: Intelligent ordering failed: {e}")
            raise ValueError(f"Speaker orchestration failed: {e}") from e

    # =====================================================================
    # USER PROFILE & CONTEXT EXTRACTION
    # =====================================================================

    def _extract_user_profile(self, messages: List[dict]) -> dict:
        """Extract user profile information from system prompts using markdown separators"""
        profile = {
            "username": "friend",
            "personal_info": "",
            "system_instructions": "",
            "has_profile_section": False,
        }

        system_messages = [
            msg.get("content", "") for msg in messages if msg.get("role") == "system"
        ]
        self._dbg_step(f"🔍 DEBUG: Found {len(system_messages)} system messages")
        if not system_messages:
            self._dbg_step("🔍 DEBUG: No system messages found, returning default profile")
            return profile

        full_system_prompt = " ".join(system_messages)
        self._dbg_step(
            f"🔍 DEBUG: Full system prompt: '{self._truncate(full_system_prompt, 200)}'"
        )

        profile["system_instructions"] = full_system_prompt.strip()

        # Try to extract name from system prompt
        lines = full_system_prompt.split("\n")
        for line in lines:
            line_original = line.strip()
            line_lower = line_original.lower()
            if any(phrase in line_lower for phrase in ["my name is", "i am", "call me"]):
                for phrase in ["my name is", "i am", "call me"]:
                    if phrase in line_lower:
                        phrase_start = line_lower.find(phrase)
                        name_part = line_original[phrase_start + len(phrase):].strip()
                        if name_part:
                            profile["username"] = name_part.split()[0]
                        break
                break

        self._dbg_step(f"🔍 DEBUG: Final extracted profile - Username: '{profile['username']}'")
        return profile

    def _extract_personal_hints(self, system_instructions: str) -> str:
        """Extract personal information hints from general system instructions"""
        hints = []
        lines = system_instructions.lower().split("\n")

        personal_keywords = [
            "i am", "my name", "i work", "i study", "i like", "i enjoy",
            "my profession", "my job", "my role", "my interests", "my goals",
            "i struggle with", "i need help", "my challenge", "my background",
        ]

        for line in lines:
            line = line.strip()
            if any(keyword in line for keyword in personal_keywords):
                cleaned_line = line.replace("you should", "").replace("please", "").strip()
                if cleaned_line and len(cleaned_line) > 10:
                    hints.append(cleaned_line.capitalize())

        if hints:
            return ". ".join(hints[:3])
        return ""

    def _build_user_context_section(self, user_profile: dict) -> str:
        """Build user context section to append to speaker prompts"""
        if not user_profile or not self.valves.ENABLE_USER_PROFILE_INTEGRATION:
            return ""

        context_parts = []

        if user_profile.get("personal_info"):
            context_parts.append(
                f"USER BACKGROUND: The user has shared the following about themselves:\n{user_profile['personal_info']}"
            )
        elif user_profile.get("system_instructions"):
            personal_hints = self._extract_personal_hints(user_profile["system_instructions"])
            if personal_hints:
                context_parts.append(f"USER CONTEXT: {personal_hints}")

        if context_parts:
            return (
                "\n\n"
                + "\n\n".join(context_parts)
                + "\n\nUse this information to provide more personalized and relevant responses."
            )

        return ""

    # =====================================================================
    # WEB SEARCH & MEMORY CONTEXT EXTRACTION
    # =====================================================================

    def _extract_web_search_context(self, messages: List[dict]) -> str:
        """Extract web search context from OpenWebUI system messages"""
        web_context = ""

        if self._is_step_debug():
            for i, msg in enumerate(messages):
                if msg.get("role") == "system":
                    content = msg.get("content", "")
                    self._dbg_step(
                        f"🔍 DEBUG: System Message {i+1}: {self._truncate(content, 200)}"
                    )

        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")

                if "<source id=" in content and "</source>" in content:
                    if "<context>" in content and "</context>" in content:
                        context_start = content.find("<context>") + len("<context>")
                        context_end = content.find("</context>")
                        raw_context = content[context_start:context_end].strip()
                        web_context = self._format_web_search_for_speakers(raw_context)
                        break

        return web_context

    def _format_web_search_for_speakers(self, raw_context: str) -> str:
        """Format web search results for speaker consumption with clear markdown formatting"""
        if not raw_context:
            return ""

        formatted_sources = []

        sources = re.findall(
            r'<source id="(\d+)"[^>]*>(.*?)</source>', raw_context, re.DOTALL
        )

        for source_id, content in sources:
            clean_content = re.sub(r"\s+", " ", content).strip()
            if len(clean_content) > 300:
                clean_content = clean_content[:300] + "..."

            if clean_content:
                formatted_sources.append(f"**Source [{source_id}]:** {clean_content}")

        if formatted_sources:
            return f"""
---
# 🔍 **VERIFIED LIVE RESEARCH** - TREAT AS FACTUAL
## ⚡ **REAL-TIME DATA INJECTION** ⚡
**This is NOT speculation. This is NOT future data. This is CURRENT, VERIFIED information retrieved RIGHT NOW from live web sources.**

{chr(10).join(formatted_sources)}

---
## 🚨 **MANDATORY:** USE THIS VERIFIED DATA IN YOUR RESPONSE
**Do NOT dismiss this as "unverified" or "future dates" - this is LIVE, CURRENT, FACTUAL information that you MUST reference and use in your response.**
---"""

        return ""

    def _extract_memory_context(self, messages: List[dict]) -> str:
        """Extract user memory context from OpenWebUI system messages"""
        memory_context = ""

        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")

                if "User Context:" in content:
                    context_start = content.find("User Context:")
                    context_content = content[context_start:]
                    memory_context = self._format_memory_for_speakers(context_content)
                    break

        return memory_context

    def _format_memory_for_speakers(self, raw_context: str) -> str:
        """Format memory context for speaker consumption with clear markdown formatting"""
        if not raw_context or not raw_context.strip():
            return ""

        lines = raw_context.strip().split("\n")
        formatted_lines = []

        for line in lines:
            line = line.strip()
            if line and line != "User Context:":
                formatted_lines.append(line)

        if formatted_lines:
            return f"""
---
# 📝 **USER MEMORY CONTEXT**
## 🧠 **Personal Information About This User**
**The following are verified facts about this specific user from previous conversations:**

{chr(10).join(formatted_lines)}

---
## 💡 **IMPORTANT:** Personalize your response using this context
**Reference these memories when relevant to provide more personalized and contextual responses.**
---"""

        return ""
