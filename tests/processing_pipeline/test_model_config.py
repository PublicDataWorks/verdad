import pytest
from google.genai.types import ServiceTier, ThinkingLevel

from processing_pipeline import model_config as mc
from processing_pipeline.constants import GeminiModel
from processing_pipeline.model_config import ModelFamily, TranscriptionMethod, thinking_config


class TestDefaults:
    """With no env set, every call site gets today's production model."""

    @pytest.mark.parametrize(
        "resolver, expected",
        [
            (mc.stage1_transcription_model, GeminiModel.GEMINI_2_5_FLASH),
            (mc.stage1_detection_model, GeminiModel.GEMINI_2_5_FLASH),
            (mc.stage1_timestamp_model, GeminiModel.GEMINI_2_5_FLASH),
            (mc.stage3_main_model, GeminiModel.GEMINI_2_5_PRO),
            (mc.stage3_fallback_model, GeminiModel.GEMINI_2_5_FLASH),
            (mc.stage3_restructure_model, GeminiModel.GEMINI_2_5_FLASH),
            (mc.stage4_researcher_model, GeminiModel.GEMINI_2_5_FLASH),
            (mc.stage4_reviewer_model, GeminiModel.GEMINI_2_5_PRO),
            (mc.stage4_kb_writer_model, GeminiModel.GEMINI_2_5_FLASH),
        ],
    )
    def test_production_defaults(self, resolver, expected):
        model = resolver()
        assert model is expected
        assert model.value == expected.value

    def test_method_defaults_to_segments(self):
        assert mc.stage1_transcription_method() is TranscriptionMethod.SEGMENTS


class TestEnvOverride:
    @pytest.mark.parametrize("setting", mc.ALL_SETTINGS, ids=lambda s: s.env_var)
    def test_enum_member_is_returned_as_member(self, monkeypatch, setting):
        monkeypatch.setenv(setting.env_var, "gemini-3.5-flash-lite")
        assert mc.resolve_model(setting) is GeminiModel.GEMINI_3_5_FLASH_LITE

    def test_unknown_id_is_accepted_as_plain_string(self, monkeypatch):
        monkeypatch.setenv("STAGE3_MAIN_MODEL", "gemini-9.9-ultra-preview")
        model = mc.stage3_main_model()
        assert model == "gemini-9.9-ultra-preview"
        assert not isinstance(model, GeminiModel)

    def test_value_is_stripped(self, monkeypatch):
        monkeypatch.setenv("STAGE4_REVIEWER_MODEL", "  gemma-4-31b-it \n")
        assert mc.stage4_reviewer_model() is GeminiModel.GEMMA_4_31B_IT

    @pytest.mark.parametrize("value", ["", "   "])
    def test_empty_means_default(self, monkeypatch, value):
        # .env.sample leaves optional settings empty; empty is "use the default", as for the other optional vars
        monkeypatch.setenv("STAGE3_MAIN_MODEL", value)
        assert mc.stage3_main_model() is GeminiModel.GEMINI_2_5_PRO

    @pytest.mark.parametrize("value", ["gemini-2.5-flash # comment", "gemini 2.5", "-x", "gemini;rm"])
    def test_malformed_id_is_rejected(self, monkeypatch, value):
        monkeypatch.setenv("STAGE1_DETECTION_MODEL", value)
        with pytest.raises(ValueError, match="STAGE1_DETECTION_MODEL"):
            mc.stage1_detection_model()

    def test_models_prefix_is_accepted(self, monkeypatch):
        monkeypatch.setenv("STAGE3_FALLBACK_MODEL", "models/gemini-3.5-flash")
        assert mc.stage3_fallback_model() == "models/gemini-3.5-flash"

    def test_settings_are_read_at_call_time(self, monkeypatch):
        assert mc.stage4_researcher_model() is GeminiModel.GEMINI_2_5_FLASH
        monkeypatch.setenv("STAGE4_RESEARCHER_MODEL", "gemini-3.6-flash")
        assert mc.stage4_researcher_model() is GeminiModel.GEMINI_3_6_FLASH


class TestTranscriptionMethod:
    @pytest.mark.parametrize("value", ["transcribe", "TRANSCRIBE", " Transcribe "])
    def test_transcribe(self, monkeypatch, value):
        monkeypatch.setenv("STAGE1_TRANSCRIPTION_METHOD", value)
        assert mc.stage1_transcription_method() is TranscriptionMethod.TRANSCRIBE

    def test_open_model(self, monkeypatch):
        monkeypatch.setenv("STAGE1_TRANSCRIPTION_METHOD", "open_model")
        assert mc.stage1_transcription_method() is TranscriptionMethod.OPEN_MODEL

    def test_invalid_method_is_rejected(self, monkeypatch):
        monkeypatch.setenv("STAGE1_TRANSCRIPTION_METHOD", "whisper")
        with pytest.raises(ValueError, match="segments, transcribe, open_model"):
            mc.stage1_transcription_method()

    def test_timestamp_model_default_follows_method(self, monkeypatch):
        monkeypatch.setenv("STAGE1_TRANSCRIPTION_METHOD", "transcribe")
        assert mc.stage1_timestamp_model() is GeminiModel.GEMINI_3_5_TRANSCRIBE
        assert mc.stage1_timestamp_model(TranscriptionMethod.SEGMENTS) is GeminiModel.GEMINI_2_5_FLASH

    def test_timestamp_model_override_applies_to_either_method(self, monkeypatch):
        monkeypatch.setenv("STAGE1_TIMESTAMP_MODEL", "gemini-3.5-flash")
        assert mc.stage1_timestamp_model(TranscriptionMethod.SEGMENTS) is GeminiModel.GEMINI_3_5_FLASH
        assert mc.stage1_timestamp_model(TranscriptionMethod.TRANSCRIBE) is GeminiModel.GEMINI_3_5_FLASH


class TestModelFamily:
    @pytest.mark.parametrize(
        "model, family",
        [
            (GeminiModel.GEMINI_2_5_FLASH, ModelFamily.BUDGET),
            (GeminiModel.GEMINI_2_5_PRO, ModelFamily.BUDGET),
            (GeminiModel.GEMINI_FLASH_LATEST, ModelFamily.BUDGET),
            (GeminiModel.GEMINI_1_5_PRO, ModelFamily.BUDGET),
            (GeminiModel.GEMINI_3_1_FLASH_LITE, ModelFamily.LEVEL),
            (GeminiModel.GEMINI_3_5_FLASH_LITE, ModelFamily.LEVEL),
            (GeminiModel.GEMINI_3_8_FLASH, ModelFamily.LEVEL),
            ("models/gemini-3.6-flash", ModelFamily.LEVEL),
            ("gemini-10-flash", ModelFamily.LEVEL),
            (GeminiModel.GEMMA_4_31B_IT, ModelFamily.NONE),
            (GeminiModel.GEMMA_4_26B_A4B_IT, ModelFamily.NONE),
            ("models/gemma-4-31b-it", ModelFamily.NONE),
        ],
    )
    def test_family(self, model, family):
        assert mc.model_family(model) is family


class TestThinkingConfig:
    @pytest.mark.parametrize("budget", [0, 1024, 2048, 4096])
    def test_gemini_2_5_flash_keeps_budget(self, budget):
        config = thinking_config(GeminiModel.GEMINI_2_5_FLASH, budget=budget)
        assert config.thinking_budget == budget
        assert config.thinking_level is None

    def test_gemini_2_5_pro_cannot_turn_thinking_off(self):
        assert thinking_config(GeminiModel.GEMINI_2_5_PRO, budget=0).thinking_budget == 128
        assert thinking_config(GeminiModel.GEMINI_2_5_PRO, budget=4096).thinking_budget == 4096

    @pytest.mark.parametrize(
        "budget, level",
        [
            (0, ThinkingLevel.MINIMAL),
            (1, ThinkingLevel.LOW),
            (1024, ThinkingLevel.LOW),
            (1025, ThinkingLevel.MEDIUM),
            (2048, ThinkingLevel.MEDIUM),
            (4096, ThinkingLevel.MEDIUM),
            (4097, ThinkingLevel.HIGH),
            (24576, ThinkingLevel.HIGH),
        ],
    )
    def test_gemini_3_maps_budget_to_level(self, budget, level):
        config = thinking_config(GeminiModel.GEMINI_3_5_FLASH_LITE, budget=budget)
        assert config.thinking_level == level
        assert config.thinking_budget is None  # 3.x rejects thinking_budget with 400

    @pytest.mark.parametrize("ask", [{"budget": 0}, {"level": "minimal"}])
    def test_gemini_3_8_flash_gets_low_instead_of_minimal(self, ask):
        # 3.8 Flash returns 400 on thinking_level=minimal (live API, Oct 30).
        assert thinking_config(GeminiModel.GEMINI_3_8_FLASH, **ask).thinking_level == ThinkingLevel.LOW

    def test_gemini_3_explicit_level_wins_over_budget(self):
        config = thinking_config(GeminiModel.GEMINI_3_5_FLASH, budget=0, level="high")
        assert config.thinking_level == ThinkingLevel.HIGH
        assert config.thinking_budget is None

    def test_gemini_3_include_thoughts_is_kept(self):
        config = thinking_config(GeminiModel.GEMINI_3_8_FLASH, budget=4096, include_thoughts=True)
        assert config.thinking_level == ThinkingLevel.MEDIUM
        assert config.include_thoughts is True

    def test_gemini_3_dynamic_budget_leaves_level_to_server(self):
        assert thinking_config(GeminiModel.GEMINI_3_5_FLASH, budget=-1) is None
        config = thinking_config(GeminiModel.GEMINI_3_5_FLASH, budget=-1, include_thoughts=True)
        assert config.thinking_level is None
        assert config.include_thoughts is True

    @pytest.mark.parametrize("model", [GeminiModel.GEMMA_4_31B_IT, GeminiModel.GEMMA_4_26B_A4B_IT])
    def test_gemma_gets_no_thinking_config(self, model):
        assert thinking_config(model, budget=4096) is None
        assert thinking_config(model, level="low") is None
        assert thinking_config(model, budget=4096, include_thoughts=True) is None

    def test_gemini_2_5_given_only_a_level(self):
        assert thinking_config(GeminiModel.GEMINI_2_5_FLASH, level="minimal").thinking_budget == 0
        assert thinking_config(GeminiModel.GEMINI_2_5_FLASH, level="medium").thinking_budget == 4096
        assert thinking_config(GeminiModel.GEMINI_2_5_FLASH, level="high").thinking_budget == -1

    def test_nothing_asked_means_no_config(self):
        assert thinking_config(GeminiModel.GEMINI_2_5_FLASH) is None
        assert thinking_config(GeminiModel.GEMINI_3_5_FLASH) is None

    def test_include_thoughts_alone_on_2_5(self):
        config = thinking_config(GeminiModel.GEMINI_2_5_PRO, include_thoughts=True)
        assert config.include_thoughts is True
        assert config.thinking_budget is None

    def test_unknown_level_is_rejected(self):
        with pytest.raises(ValueError, match="minimal, low, medium, high"):
            thinking_config(GeminiModel.GEMINI_3_5_FLASH, level="extreme")

    def test_level_is_case_insensitive(self):
        assert thinking_config(GeminiModel.GEMINI_3_5_FLASH, level="LOW").thinking_level == ThinkingLevel.LOW

    def test_plain_string_model(self):
        assert thinking_config("gemini-3.9-flash-preview", budget=1024).thinking_level == ThinkingLevel.LOW
        assert thinking_config("gemini-2.0-flash", budget=1024).thinking_budget == 1024


def test_enum_keeps_existing_values():
    assert GeminiModel.GEMINI_2_5_FLASH.value == "gemini-2.5-flash"
    assert GeminiModel.GEMINI_2_5_PRO.value == "gemini-2.5-pro"
    assert str(GeminiModel.GEMINI_3_5_TRANSCRIBE) == "gemini-3.5-transcribe"
    assert GeminiModel("gemma-4-26b-a4b-it") is GeminiModel.GEMMA_4_26B_A4B_IT


class TestStage1FlowOptions:
    """STAGE1_TRANSCRIBE_FIRST / STAGE1_DETECTION_PASSES / STAGE1_ANCHOR_TIMESTAMPS; unset is today's flow."""

    def test_defaults_are_todays_flow(self):
        assert mc.stage1_flow_options() == mc.Stage1FlowOptions(
            transcribe_first=False, detection_passes=mc.DetectionPasses.TWO, anchor_timestamps=False
        )

    def test_fully_streamlined(self, monkeypatch):
        monkeypatch.setenv("STAGE1_TRANSCRIPTION_METHOD", "transcribe")
        monkeypatch.setenv("STAGE1_TRANSCRIBE_FIRST", "true")
        monkeypatch.setenv("STAGE1_DETECTION_PASSES", "ONE")
        monkeypatch.setenv("STAGE1_ANCHOR_TIMESTAMPS", "1")
        assert mc.stage1_flow_options() == mc.Stage1FlowOptions(True, mc.DetectionPasses.ONE, True)

    @pytest.mark.parametrize("value, expected", [("", False), ("false", False), ("0", False), ("Off", False), ("YES", True), ("on", True)])
    def test_flag_spellings(self, monkeypatch, value, expected):
        monkeypatch.setenv("STAGE1_ANCHOR_TIMESTAMPS", value)
        assert mc.stage1_anchor_timestamps() is expected

    def test_stage3_repeat_dedup_is_off_by_default(self, monkeypatch):
        monkeypatch.delenv("STAGE3_REPEAT_DEDUP", raising=False)
        assert mc.stage3_repeat_dedup() is False

    def test_stage3_repeat_dedup_on(self, monkeypatch):
        monkeypatch.setenv("STAGE3_REPEAT_DEDUP", "true")
        assert mc.stage3_repeat_dedup() is True


class TestStage3ServiceTier:
    @pytest.mark.parametrize("value", [None, "", "standard", " Standard "])
    def test_standard_unless_flex(self, monkeypatch, value):
        if value is None:
            monkeypatch.delenv("STAGE3_SERVICE_TIER", raising=False)
        else:
            monkeypatch.setenv("STAGE3_SERVICE_TIER", value)
        assert mc.stage3_service_tier() is None

    @pytest.mark.parametrize("value", ["flex", "FLEX"])
    def test_flex(self, monkeypatch, value):
        monkeypatch.setenv("STAGE3_SERVICE_TIER", value)
        assert mc.stage3_service_tier() is ServiceTier.FLEX

    @pytest.mark.parametrize("value", ["priority", "batch"])
    def test_other_values_raise(self, monkeypatch, value):
        monkeypatch.setenv("STAGE3_SERVICE_TIER", value)
        with pytest.raises(ValueError, match=f"STAGE3_SERVICE_TIER='{value}'"):
            mc.stage3_service_tier()

    def test_unknown_flag_value(self, monkeypatch):
        monkeypatch.setenv("STAGE1_ANCHOR_TIMESTAMPS", "maybe")
        with pytest.raises(ValueError, match="STAGE1_ANCHOR_TIMESTAMPS='maybe'"):
            mc.stage1_flow_options()

    def test_transcribe_first_needs_the_transcribe_method(self, monkeypatch):
        monkeypatch.setenv("STAGE1_TRANSCRIBE_FIRST", "true")
        with pytest.raises(ValueError, match="needs STAGE1_TRANSCRIPTION_METHOD=transcribe"):
            mc.stage1_flow_options()

    def test_transcribe_first_with_open_models(self, monkeypatch):
        monkeypatch.setenv("STAGE1_TRANSCRIPTION_METHOD", "open_model")
        monkeypatch.setenv("STAGE1_TRANSCRIBE_FIRST", "true")
        assert mc.stage1_flow_options().transcribe_first is True

    def test_open_models_need_transcribe_first(self, monkeypatch):
        monkeypatch.setenv("STAGE1_TRANSCRIPTION_METHOD", "open_model")
        with pytest.raises(ValueError, match="open_model needs STAGE1_TRANSCRIBE_FIRST=true"):
            mc.stage1_flow_options()

    def test_one_pass_needs_transcribe_first(self, monkeypatch):
        monkeypatch.setenv("STAGE1_TRANSCRIPTION_METHOD", "transcribe")
        monkeypatch.setenv("STAGE1_DETECTION_PASSES", "one")
        with pytest.raises(ValueError, match="STAGE1_DETECTION_PASSES=one needs STAGE1_TRANSCRIBE_FIRST=true"):
            mc.stage1_flow_options()

    def test_unknown_pass_count(self, monkeypatch):
        monkeypatch.setenv("STAGE1_DETECTION_PASSES", "three")
        with pytest.raises(ValueError, match="expected one of: two, one"):
            mc.stage1_flow_options()

    def test_explicit_two_passes(self, monkeypatch):
        monkeypatch.setenv("STAGE1_DETECTION_PASSES", "two")
        assert mc.stage1_flow_options().detection_passes is mc.DetectionPasses.TWO


class TestStage1FileWorkers:
    def test_default_is_one_file_at_a_time(self, monkeypatch):
        monkeypatch.delenv("STAGE1_FILE_WORKERS", raising=False)
        assert mc.stage1_file_workers() == 1

    def test_reads_the_env(self, monkeypatch):
        monkeypatch.setenv("STAGE1_FILE_WORKERS", " 3 ")
        assert mc.stage1_file_workers() == 3

    @pytest.mark.parametrize("value", ["0", "-2", "two"])
    def test_rejects_anything_but_a_positive_count(self, monkeypatch, value):
        monkeypatch.setenv("STAGE1_FILE_WORKERS", value)
        with pytest.raises(ValueError, match=f"STAGE1_FILE_WORKERS='{value}'"):
            mc.stage1_file_workers()


class TestStage2ClipOptions:
    """STAGE2_USE_WORD_TIMES / STAGE2_CONTEXT_BEFORE_S / STAGE2_CONTEXT_AFTER_S; unset is today's clipping."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        for name in ("STAGE2_USE_WORD_TIMES", "STAGE2_CONTEXT_BEFORE_S", "STAGE2_CONTEXT_AFTER_S"):
            monkeypatch.delenv(name, raising=False)

    def test_unset_is_off_with_the_flow_padding(self):
        assert mc.stage2_clip_options(90, 60) == mc.Stage2ClipOptions(
            use_word_times=False, context_before_s=90.0, context_after_s=60.0
        )

    def test_padding_follows_the_flow_parameters_when_unset(self):
        options = mc.stage2_clip_options(30, 15)
        assert (options.context_before_s, options.context_after_s) == (30.0, 15.0)

    def test_env_overrides_with_float_seconds(self, monkeypatch):
        monkeypatch.setenv("STAGE2_USE_WORD_TIMES", "true")
        monkeypatch.setenv("STAGE2_CONTEXT_BEFORE_S", "45.5")
        monkeypatch.setenv("STAGE2_CONTEXT_AFTER_S", " 0 ")
        assert mc.stage2_clip_options(90, 60) == mc.Stage2ClipOptions(
            use_word_times=True, context_before_s=45.5, context_after_s=0.0
        )

    def test_empty_values_mean_unset(self, monkeypatch):
        monkeypatch.setenv("STAGE2_USE_WORD_TIMES", "")
        monkeypatch.setenv("STAGE2_CONTEXT_BEFORE_S", "")
        assert mc.stage2_clip_options(90, 60).use_word_times is False
        assert mc.stage2_clip_options(90, 60).context_before_s == 90.0

    @pytest.mark.parametrize("value", ["abc", "-1", "nan", "inf"])
    def test_bad_padding_raises(self, monkeypatch, value):
        monkeypatch.setenv("STAGE2_CONTEXT_AFTER_S", value)
        with pytest.raises(ValueError, match="STAGE2_CONTEXT_AFTER_S="):
            mc.stage2_clip_options(90, 60)

    def test_bad_flag_raises(self, monkeypatch):
        monkeypatch.setenv("STAGE2_USE_WORD_TIMES", "maybe")
        with pytest.raises(ValueError, match="STAGE2_USE_WORD_TIMES='maybe'"):
            mc.stage2_clip_options(90, 60)
