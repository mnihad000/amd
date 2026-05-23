from __future__ import annotations

import base64
import json
import mimetypes
from abc import ABC, abstractmethod
from pathlib import Path
from urllib import error, request

from .config import LabelConfig
from .contracts import ClassQualityConfig, LabelBox, LabelRecord, SampleRecord
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


def validate_label_records_with_review(
    label_records: list[LabelRecord],
    admitted_classes: list[str],
    min_confidence: float,
    class_quality: ClassQualityConfig,
) -> tuple[list[LabelRecord], list[LabelRecord], dict[str, object]]:
    valid: list[LabelRecord] = []
    invalid: list[LabelRecord] = []
    review_items: list[dict[str, object]] = []
    admitted_set = set(admitted_classes)

    for record in label_records:
        notes = list(record.notes)
        validated_boxes: list[LabelBox] = []
        review_reasons_by_box = _review_reasons_by_box(
            record.boxes,
            admitted_set,
            min_confidence,
            class_quality,
        )

        for index, box in enumerate(record.boxes):
            if box.class_name not in admitted_set:
                notes.append(f"Ignored box for non-admitted class '{box.class_name}'.")
                continue
            reasons = review_reasons_by_box.get(index, [])
            if reasons:
                notes.extend(f"Review required: {reason}." for reason in reasons)
                review_items.append(
                    {
                        "id": f"{record.sample_id}:{index}",
                        "sample_id": record.sample_id,
                        "provider": record.provider,
                        "state": "pending",
                        "reasons": reasons,
                        "box": {
                            "class_name": box.class_name,
                            "class_id": box.class_id,
                            "x_center": box.x_center,
                            "y_center": box.y_center,
                            "width": box.width,
                            "height": box.height,
                            "confidence": box.confidence,
                        },
                        "notes": [],
                    }
                )
                continue
            validated_boxes.append(box)

        record.boxes = validated_boxes
        record.notes = notes
        if validated_boxes:
            record.status = "validated"
            valid.append(record)
        else:
            record.status = "invalid"
            invalid.append(record)

    review_queue = {
        "schema_version": 1,
        "states": ["pending", "approved", "relabel_requested", "rejected"],
        "items": review_items,
    }
    return valid, invalid, review_queue


def _review_reasons_by_box(
    boxes: list[LabelBox],
    admitted_set: set[str],
    min_confidence: float,
    class_quality: ClassQualityConfig,
) -> dict[int, list[str]]:
    reasons: dict[int, list[str]] = {}

    for index, box in enumerate(boxes):
        box_reasons: list[str] = []
        if box.class_name not in admitted_set:
            continue
        if box.confidence < max(min_confidence, class_quality.review_confidence_threshold):
            box_reasons.append("low confidence")
        if not _box_geometry_is_sufficient(box):
            box_reasons.append("insufficient box geometry")
        if box_reasons:
            reasons[index] = box_reasons

    for left_index, left in enumerate(boxes):
        if left.class_name not in admitted_set:
            continue
        for right_index in range(left_index + 1, len(boxes)):
            right = boxes[right_index]
            if right.class_name not in admitted_set:
                continue
            iou = _box_iou(left, right)
            if iou < class_quality.conflict_iou_threshold:
                continue
            reason = "cross-class conflict" if left.class_name != right.class_name else "ambiguous overlap"
            reasons.setdefault(left_index, []).append(reason)
            reasons.setdefault(right_index, []).append(reason)

    return {
        index: list(dict.fromkeys(box_reasons))
        for index, box_reasons in reasons.items()
    }


def _box_geometry_is_sufficient(box: LabelBox) -> bool:
    if not 0.0 <= box.x_center <= 1.0 or not 0.0 <= box.y_center <= 1.0:
        return False
    if not 0.0 < box.width <= 1.0 or not 0.0 < box.height <= 1.0:
        return False
    return box.width * box.height >= 0.0001


def _box_edges(box: LabelBox) -> tuple[float, float, float, float]:
    half_width = box.width / 2.0
    half_height = box.height / 2.0
    return (
        max(0.0, box.x_center - half_width),
        max(0.0, box.y_center - half_height),
        min(1.0, box.x_center + half_width),
        min(1.0, box.y_center + half_height),
    )


def _box_iou(left: LabelBox, right: LabelBox) -> float:
    left_x1, left_y1, left_x2, left_y2 = _box_edges(left)
    right_x1, right_y1, right_x2, right_y2 = _box_edges(right)
    inter_width = max(0.0, min(left_x2, right_x2) - max(left_x1, right_x1))
    inter_height = max(0.0, min(left_y2, right_y2) - max(left_y1, right_y1))
    intersection = inter_width * inter_height
    left_area = max(0.0, left_x2 - left_x1) * max(0.0, left_y2 - left_y1)
    right_area = max(0.0, right_x2 - right_x1) * max(0.0, right_y2 - right_y1)
    union = left_area + right_area - intersection
    if union <= 0.0:
        return 0.0
    return intersection / union
