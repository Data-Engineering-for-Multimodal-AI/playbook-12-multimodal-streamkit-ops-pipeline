#!/usr/bin/env python3
"""
Download LEMMA-RCA dataset from HuggingFace.

This script downloads the Cloud Computing Preprocessed dataset from the
HuggingFace repository and extracts it into the data/{case}/ directory.

Usage:
    python download_data.py                  # Download case 20240115 (default)
    python download_data.py --case 20240207  # Download a specific case
"""

import argparse
import os
import sys
import zipfile
from pathlib import Path
from typing import Optional

from huggingface_hub import hf_hub_download, HfApi, list_repo_files


REPO_ID = "Lemma-RCA-NEC/Cloud_Computing_Preprocessed"
VALID_CASES = ["20231207", "20231221", "20240115", "20240124", "20240207", "20240215"]


def list_available_files(repo_id: str) -> list[str]:
    """List all files available in the HuggingFace repository."""
    try:
        files = list_repo_files(repo_id=repo_id, repo_type="dataset")
        return files
    except Exception as e:
        print(f"Error listing files: {e}")
        return []


def download_and_extract(
    case: str,
    repo_id: str = REPO_ID,
    output_dir: Optional[str] = None,
) -> bool:
    """
    Download and extract LEMMA-RCA dataset for a specific case.

    Args:
        case: Case ID (e.g., '20240115')
        repo_id: HuggingFace repository ID
        output_dir: Output directory (default: data/{case}/)

    Returns:
        True if successful, False otherwise
    """
    if case not in VALID_CASES:
        print(f"Error: Invalid case '{case}'")
        print(f"Valid cases: {', '.join(VALID_CASES)}")
        return False

    if output_dir is None:
        output_dir = f"data/{case}"

    # Create output directory
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    print(f"Downloading LEMMA-RCA dataset for case {case}...")
    print(f"Repository: {repo_id}")
    print(f"Output directory: {output_dir}")

    # List available files in the repository
    available_files = list_available_files(repo_id)
    print(f"\nFound {len(available_files)} files in repository")

    # Identify relevant files for this case
    case_files = [
        f for f in available_files
        if case in f and f.endswith('.zip')
    ]

    if not case_files:
        print(f"\nWarning: No zip files found for case {case}")
        print("Available files containing case ID:")
        case_related = [f for f in available_files if case in f]
        for f in case_related[:10]:  # Show first 10
            print(f"  {f}")
        return False

    print(f"\nFound {len(case_files)} zip files for case {case}:")
    for f in case_files:
        print(f"  {f}")

    # Download and extract each zip file
    successful_downloads = 0
    for filename in case_files:
        try:
            print(f"\nDownloading {filename}...")
            file_path = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                repo_type="dataset",
            )
            print(f"  Downloaded to: {file_path}")

            # Extract the zip file
            print(f"  Extracting to {output_dir}...")
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(output_dir)
            print(f"  Extraction complete")
            successful_downloads += 1

        except Exception as e:
            print(f"Error downloading/extracting {filename}: {e}")

    if successful_downloads == 0:
        print("\nError: Failed to download any files")
        return False

    # Validate extracted files
    print(f"\nValidating extracted files...")
    required_files = [
        'kpi.csv',
        'pod_level_log_golden_signal.npy',
        'pod_level_log_frequency.npy',
    ]

    extracted_files = list(Path(output_dir).rglob('*.npy')) + \
                      list(Path(output_dir).rglob('*.csv'))
    extracted_names = [f.name for f in extracted_files]

    print(f"Found {len(extracted_files)} data files:")
    for name in sorted(extracted_names):
        print(f"  {name}")

    # Check for metric files
    metric_files = [f for f in extracted_names if f.startswith('pod_level_data_')]
    if metric_files:
        print(f"\nMetric files ({len(metric_files)}):")
        for name in sorted(metric_files):
            print(f"  {name}")

    # Verify required files
    missing_files = []
    for req_file in required_files:
        if not any(req_file in name for name in extracted_names):
            missing_files.append(req_file)

    if missing_files:
        print(f"\nWarning: Some expected files may be missing:")
        for f in missing_files:
            print(f"  {f}")
    else:
        print(f"\nAll required files found!")

    print(f"\nDataset successfully downloaded and extracted to {output_dir}")
    return True


def main():
    """Command-line interface for downloading LEMMA-RCA dataset."""
    parser = argparse.ArgumentParser(
        description="Download LEMMA-RCA dataset from HuggingFace"
    )
    parser.add_argument(
        "--case",
        type=str,
        default="20240115",
        help=f"Case ID to download (default: 20240115). "
             f"Valid: {', '.join(VALID_CASES)}",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: data/{case}/)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available cases",
    )

    args = parser.parse_args()

    if args.list:
        print("Valid cases:", ", ".join(VALID_CASES))
        return 0

    success = download_and_extract(
        case=args.case,
        output_dir=args.output_dir,
    )

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
