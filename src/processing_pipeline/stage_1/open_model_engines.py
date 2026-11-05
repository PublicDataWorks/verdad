"""The GPU models behind ``OpenModelTranscriber`` (requirements-gpu.txt, CUDA); Whisper loads once per flow run, the Arabic models once per Arabic recording.

OPEN_MODEL_COHERE_PATH: a local copy of the Cohere model, else it downloads from Hugging Face.
"""

import gc
import os
from functools import cached_property

import torch
import torchaudio.functional as F
from fairseq2 import gang
from fairseq2.nn import BatchLayout
from faster_whisper import BatchedInferencePipeline, WhisperModel, decode_audio
from faster_whisper.vad import VadOptions, get_speech_timestamps
from omnilingual_asr.models.inference.pipeline import ASRInferencePipeline
from transformers import AutoProcessor, CohereAsrForConditionalGeneration

from processing_pipeline.stage_1.open_model_executor import SAMPLE_RATE, ctc_min_frames

COHERE_DEFAULT = "CohereLabs/cohere-transcribe-arabic-07-2026"
ALIGNER_CARD = "omniASR_CTC_1B_v2"
VAD_THRESHOLD = 0.1
MIN_SPEECH_SECONDS = 5
WHISPER_BATCH = 16
COHERE_BATCH = 8


class GpuEngines:
    def load_audio(self, audio_file):
        return decode_audio(audio_file, sampling_rate=SAMPLE_RATE)

    @cached_property
    def whisper(self):
        return WhisperModel("large-v3", device="cuda", compute_type="float16")

    @cached_property
    def cohere(self):
        path = os.getenv("OPEN_MODEL_COHERE_PATH") or COHERE_DEFAULT
        processor = AutoProcessor.from_pretrained(path)
        model = CohereAsrForConditionalGeneration.from_pretrained(path, device_map="cuda:0")
        return processor, model

    @cached_property
    def aligner(self):
        # fairseq2 0.6 creates this per-thread list only in the importing thread; models load on the gpu thread
        gang._thread_local.__dict__.setdefault("current_gangs", [])
        return ASRInferencePipeline(model_card=ALIGNER_CARD)

    def release_arabic(self):
        self.__dict__.pop("cohere", None)
        self.__dict__.pop("aligner", None)
        gc.collect()
        torch.cuda.empty_cache()

    def window_language(self, window):
        speech = (
            sum(c["end"] - c["start"] for c in get_speech_timestamps(window, VadOptions(threshold=VAD_THRESHOLD)))
            / SAMPLE_RATE
        )
        if speech < MIN_SPEECH_SECONDS:
            return None
        language, _, _ = self.whisper.detect_language(audio=window)
        return language

    def whisper_words(self, audio, language):
        segments, _ = BatchedInferencePipeline(self.whisper).transcribe(
            audio,
            batch_size=WHISPER_BATCH,
            language=language,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters={"threshold": VAD_THRESHOLD},  # a dict: the pipeline adds its 30 s chunk cap only then
            condition_on_previous_text=False,
        )
        return [{"text": w.word, "start": w.start, "end": w.end} for s in segments for w in s.words or []]

    def cohere_texts(self, chunks):
        processor, model = self.cohere
        texts = []
        for i in range(0, len(chunks), COHERE_BATCH):
            inputs = processor(
                list(chunks[i : i + COHERE_BATCH]), sampling_rate=SAMPLE_RATE, return_tensors="pt", language="ar"
            )
            inputs = inputs.to(model.device, dtype=model.dtype)
            texts += processor.batch_decode(model.generate(**inputs, max_new_tokens=256), skip_special_tokens=True)
        return texts

    def align(self, chunk, words, offset):
        """CTC forced alignment of ``words`` to the chunk; spreads them evenly when the chunk is too short for them."""
        pipe = self.aligner
        token_ids = [pipe.token_encoder(w).tolist() for w in words]
        keep = [(w, ids) for w, ids in zip(words, token_ids, strict=True) if ids]
        if not keep:
            return []
        x = torch.from_numpy(chunk.copy())
        x = ((x - x.mean()) / torch.sqrt(x.var() + 1e-5)).unsqueeze(0).to(pipe.device, pipe.dtype)
        with torch.inference_mode():
            logits, _ = pipe.model(x, BatchLayout(x.shape, seq_lens=[x.shape[1]], device=x.device))
        emission = torch.log_softmax(logits.float(), dim=-1)
        seconds_per_frame = len(chunk) / SAMPLE_RATE / emission.size(1)
        blank = pipe.tokenizer.vocab_info.bos_idx  # the CTC blank in this model (VER-448 probe)
        tokens = [t for _, ids in keep for t in ids]
        if ctc_min_frames(tokens) > emission.size(1):
            step = len(chunk) / SAMPLE_RATE / len(keep)
            return [
                {"text": w, "start": offset + i * step, "end": offset + (i + 1) * step} for i, (w, _) in enumerate(keep)
            ]
        targets = torch.tensor([tokens], dtype=torch.int32, device=emission.device)
        labels, _ = F.forced_align(emission, targets, blank=blank)
        spans = F.merge_tokens(labels[0], torch.zeros_like(labels[0], dtype=torch.float), blank=blank)
        out, k = [], 0
        for w, ids in keep:
            word_spans = spans[k : k + len(ids)]
            k += len(ids)
            out.append(
                {
                    "text": w,
                    "start": offset + word_spans[0].start * seconds_per_frame,
                    "end": offset + word_spans[-1].end * seconds_per_frame,
                }
            )
        return out
