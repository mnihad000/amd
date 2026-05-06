from __future__ import annotations

import random
import shutil
from pathlib import Path

from .contracts import DatasetBuildResult, JobPaths, LabelRecord, SampleRecord
from .utils import ensure_dir


def build_dataset(
    job_paths: JobPaths,
    samples: list[SampleRecord],
    labels: list[LabelRecord],
    admitted_classes: list[str],
) -> DatasetBuildResult:
    if not admitted_classes:
        return DatasetBuildResult(status="skipped", notes=["No admitted classes available for dataset build."])
    if not samples or not labels:
        return DatasetBuildResult(status="skipped", notes=["No validated samples or labels available."])

    dataset_dir = ensure_dir(job_paths.datasets / "dataset")
    image_dirs = {split: ensure_dir(dataset_dir / "images" / split) for split in ("train", "val", "test")}
    label_dirs = {split: ensure_dir(dataset_dir / "labels" / split) for split in ("train", "val", "test")}
    class_map = {index: class_name for index, class_name in enumerate(admitted_classes)}
    class_lookup = {name: index for index, name in class_map.items()}

    labels_by_sample = {record.sample_id: record for record in labels}
    usable_samples = [sample for sample in samples if sample.id in labels_by_sample]
    if not usable_samples:
        return DatasetBuildResult(status="skipped", notes=["No samples have validated labels for admitted classes."])

    splits = _split_samples(usable_samples)
    split_counts: dict[str, int] = {}

    for split_name, split_samples in splits.items():
        split_counts[split_name] = len(split_samples)
        for sample in split_samples:
            source_path = Path(sample.path)
            image_target = image_dirs[split_name] / source_path.name
            shutil.copy2(source_path, image_target)

            label_target = label_dirs[split_name] / f"{source_path.stem}.txt"
            record = labels_by_sample[sample.id]
            lines = [
                f"{class_lookup[box.class_name]} {box.x_center:.6f} {box.y_center:.6f} "
                f"{box.width:.6f} {box.height:.6f}"
                for box in record.boxes
                if box.class_name in class_lookup
            ]
            label_target.write_text("\n".join(lines), encoding="utf-8")
            record.label_path = str(label_target)

    data_yaml_path = dataset_dir / "data.yaml"
    data_yaml_path.write_text(_render_data_yaml(dataset_dir, class_map), encoding="utf-8")

    return DatasetBuildResult(
        status="completed",
        dataset_dir=str(dataset_dir),
        data_yaml_path=str(data_yaml_path),
        class_map=class_map,
        split_counts=split_counts,
    )


def _split_samples(samples: list[SampleRecord]) -> dict[str, list[SampleRecord]]:
    randomizer = random.Random(42)
    shuffled = list(samples)
    randomizer.shuffle(shuffled)

    total = len(shuffled)
    train_cutoff = max(1, int(total * 0.7))
    val_cutoff = max(train_cutoff + 1, int(total * 0.9)) if total > 1 else total

    return {
        "train": shuffled[:train_cutoff],
        "val": shuffled[train_cutoff:val_cutoff],
        "test": shuffled[val_cutoff:],
    }


def _render_data_yaml(dataset_dir: Path, class_map: dict[int, str]) -> str:
    names = "\n".join(f"  {index}: {name}" for index, name in class_map.items())
    return (
        f"path: {dataset_dir}\n"
        "train: images/train\n"
        "val: images/val\n"
        "test: images/test\n\n"
        "names:\n"
        f"{names}\n"
    )
