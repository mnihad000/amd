from __future__ import annotations

import base64
import json
import mimetypes
from abc import ABC, abstractmethod
from pathlib import Path
from urllib import error, request

from .config import LabelConfig
from .contracts import LabelBox, LabelRecord, SampleRecord
from .utils import strip_code_fences


class LabelProvider(ABC):
    name: str

    @abstractmethod
    def label_samples(
        self,
        samples: list[SampleRecord],
        admitted_classes: list[str],
        class_map: dict[str, int],
    ) -> list[LabelRecord]:
        raise NotImplementedError


class MockLabelProvider(LabelProvider):
    name = "mock"

    def label_samples(
        self,
        samples: list[SampleRecord],
        admitted_classes: list[str],
        class_map: dict[str, int],
    ) -> list[LabelRecord]:
        records: list[LabelRecord] = []
        admitted_set = set(admitted_classes)

        for sample in samples:
            boxes: list[LabelBox] = []
            for class_name in sample.class_names:
                if class_name not in admitted_set:
                    continue
                boxes.append(
                    LabelBox(
                        class_name=class_name,
                        class_id=class_map[class_name],
                        x_center=0.5,
                        y_center=0.5,
                        width=0.4,
                        height=0.4,
                        confidence=float(sample.metadata.get("mock_confidence", 0.92)),
                    )
                )

            status = "ok" if boxes else "skipped"
            notes = [] if boxes else ["No admitted classes matched the sample."]
            records.append(
                LabelRecord(
                    sample_id=sample.id,
                    provider=self.name,
                    status=status,
                    boxes=boxes,
                    notes=notes,
                )
            )
        return records


class GeminiLabelProvider(LabelProvider):
    name = "gemini"

    def __init__(self, config: LabelConfig) -> None:
        if not config.api_key:
            raise ValueError("LABEL_API_KEY is required when LABEL_PROVIDER=gemini.")
        self.api_key = config.api_key
        self.model = config.gemini_model

    def label_samples(
        self,
        samples: list[SampleRecord],
        admitted_classes: list[str],
        class_map: dict[str, int],
    ) -> list[LabelRecord]:
        return [self._label_single_sample(sample, admitted_classes, class_map) for sample in samples]

    def _label_single_sample(
        self,
        sample: SampleRecord,
        admitted_classes: list[str],
        class_map: dict[str, int],
    ) -> LabelRecord:
        image_path = Path(sample.path)
        mime_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
        encoded_image = base64.b64encode(image_path.read_bytes()).decode("utf-8")
        prompt = self._build_prompt(admitted_classes)
        endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": mime_type, "data": encoded_image}},
                    ],
                }
            ]
        }

        request_body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            endpoint,
            data=request_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(http_request, timeout=60) as response:
                raw_response = response.read().decode("utf-8")
        except error.URLError as exc:
            return LabelRecord(
                sample_id=sample.id,
                provider=self.name,
                status="error",
                notes=[f"Gemini API request failed: {exc}"],
            )

        try:
            parsed_response = json.loads(raw_response)
            text = parsed_response["candidates"][0]["content"]["parts"][0]["text"]
            payload_text = strip_code_fences(text)
            payload_json = json.loads(payload_text)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            return LabelRecord(
                sample_id=sample.id,
                provider=self.name,
                status="error",
                notes=[f"Failed to parse Gemini response: {exc}"],
            )

        boxes: list[LabelBox] = []
        for item in payload_json.get("boxes", []):
            class_name = str(item.get("class_name", "")).strip().lower()
            if class_name not in class_map:
                continue
            boxes.append(
                LabelBox(
                    class_name=class_name,
                    class_id=class_map[class_name],
                    x_center=float(item["x_center"]),
                    y_center=float(item["y_center"]),
                    width=float(item["width"]),
                    height=float(item["height"]),
                    confidence=float(item.get("confidence", 0.0)),
                )
            )

        return LabelRecord(
            sample_id=sample.id,
            provider=self.name,
            status="ok" if boxes else "skipped",
            boxes=boxes,
            notes=[] if boxes else ["Gemini returned no usable boxes."],
        )

    @staticmethod
    def _build_prompt(admitted_classes: list[str]) -> str:
        classes = ", ".join(admitted_classes)
        return (
            "You are labeling an object-detection training image. "
            f"Only detect these classes: {classes}. "
            "Return strict JSON with the shape "
            '{"boxes":[{"class_name":"...", "x_center":0.5, "y_center":0.5, '
            '"width":0.2, "height":0.3, "confidence":0.9}]}. '
            "All coordinates must be normalized to the [0,1] range."
        )


def build_label_provider(config: LabelConfig) -> LabelProvider:
    provider_name = config.provider.strip().lower()
    if provider_name == "mock":
        return MockLabelProvider()
    if provider_name == "gemini":
        return GeminiLabelProvider(config)
    raise ValueError(f"Unsupported label provider: {config.provider}")


def validate_label_records(
    label_records: list[LabelRecord],
    admitted_classes: list[str],
    min_confidence: float,
) -> tuple[list[LabelRecord], list[LabelRecord]]:
    valid: list[LabelRecord] = []
    invalid: list[LabelRecord] = []
    admitted_set = set(admitted_classes)

    for record in label_records:
        record_valid = True
        validated_boxes: list[LabelBox] = []
        notes = list(record.notes)

        for box in record.boxes:
            if box.class_name not in admitted_set:
                notes.append(f"Ignored box for non-admitted class '{box.class_name}'.")
                continue
            if not 0.0 <= box.x_center <= 1.0 or not 0.0 <= box.y_center <= 1.0:
                notes.append("Box center is outside normalized bounds.")
                record_valid = False
                continue
            if not 0.0 < box.width <= 1.0 or not 0.0 < box.height <= 1.0:
                notes.append("Box width or height is outside normalized bounds.")
                record_valid = False
                continue
            if box.confidence < min_confidence:
                notes.append("Box confidence is below the configured threshold.")
                record_valid = False
                continue
            validated_boxes.append(box)

        record.boxes = validated_boxes
        record.notes = notes
        if not validated_boxes:
            record_valid = False

        if record_valid:
            record.status = "validated"
            valid.append(record)
        else:
            record.status = "invalid"
            invalid.append(record)

    return valid, invalid
