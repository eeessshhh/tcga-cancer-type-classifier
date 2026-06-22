import requests
import os
import csv
import time
import boto3

# --- CONFIG ---
BUCKET = "cancer-source-data"
S3_PREFIX = "raw/tcga/"
DOWNLOAD_DIR = "data/raw"
MANIFEST_PATH = "data/manifest.csv"

# Start at 100/class to validate the full pipeline cheaply and quickly.
# All 5 projects have well over 400 available, so you can raise this
# later (up to ~400) just by changing this number and re-running.
TARGET_PER_PROJECT = 100

PROJECTS = [
    "TCGA-BRCA",   # Breast cancer
    "TCGA-LUAD",   # Lung adenocarcinoma
    "TCGA-COAD",   # Colon cancer
    "TCGA-PRAD",   # Prostate cancer
    "TCGA-KIRC",   # Kidney cancer
]

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
s3 = boto3.client("s3")


def get_maf_file_ids(project_id, size):
    """Query GDC for up to `size` open-access masked somatic mutation MAFs for a project."""
    url = "https://api.gdc.cancer.gov/files"
    filters = {
        "op": "and",
        "content": [
            {"op": "=", "content": {"field": "cases.project.project_id", "value": project_id}},
            {"op": "=", "content": {"field": "data_type", "value": "Masked Somatic Mutation"}},
            {"op": "=", "content": {"field": "data_format", "value": "MAF"}},
            {"op": "=", "content": {"field": "access", "value": "open"}},
        ]
    }
    response = requests.post(
        url,
        json={"filters": filters, "fields": "file_id,file_name,file_size", "size": size},
    )
    response.raise_for_status()
    return response.json()["data"]["hits"]


def download_file(file_id, file_name):
    url = f"https://api.gdc.cancer.gov/data/{file_id}"
    local_path = os.path.join(DOWNLOAD_DIR, file_name)
    response = requests.get(url, stream=True, timeout=60)
    response.raise_for_status()
    with open(local_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    return local_path


def upload_to_s3(local_path, file_name):
    s3.upload_file(local_path, BUCKET, S3_PREFIX + file_name)


# ---- MAIN ----
manifest_rows = []

for project in PROJECTS:
    cancer_type = project.replace("TCGA-", "")
    print(f"\n=== {project} (target: {TARGET_PER_PROJECT}) ===")

    hits = get_maf_file_ids(project, TARGET_PER_PROJECT)
    print(f"  GDC returned {len(hits)} files")

    if not hits:
        print(f"  No open-access MAF found for {project} — skipping")
        continue

    for i, f in enumerate(hits):
        file_id = f["file_id"]
        file_name = f["file_name"]

        try:
            local_path = download_file(file_id, file_name)
            upload_to_s3(local_path, file_name)
            os.remove(local_path)  # don't pile up local copies once it's safely in S3

            # We know the cancer type for certain right now -- record it,
            # so the Glue job never has to guess or call GDC again.
            manifest_rows.append({"file_name": file_name, "cancer_type": cancer_type})

            if (i + 1) % 20 == 0 or (i + 1) == len(hits):
                print(f"  [{i+1}/{len(hits)}] uploaded ({file_name})")

        except Exception as e:
            print(f"  ERROR on {file_name}: {e}")

        time.sleep(0.1)  # be polite to GDC's public API

print(f"\nTotal files downloaded: {len(manifest_rows)}")

with open(MANIFEST_PATH, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["file_name", "cancer_type"])
    writer.writeheader()
    writer.writerows(manifest_rows)

s3.upload_file(MANIFEST_PATH, BUCKET, S3_PREFIX + "manifest.csv")
print(f"Manifest uploaded to s3://{BUCKET}/{S3_PREFIX}manifest.csv")