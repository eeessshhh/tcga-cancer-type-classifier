import boto3
import pandas as pd
import io

s3 = boto3.client('s3')
BUCKET = 'cancer-source-data'
RAW_PREFIX = 'raw/tcga/'
OUTPUT_PREFIX = 'processed/clean_maf/'
MANIFEST_KEY = RAW_PREFIX + 'manifest.csv'

KEEP_COLS = [
    'Hugo_Symbol',
    'Tumor_Sample_Barcode',
    'Variant_Classification',
    'Variant_Type',
    'IMPACT',
    'One_Consequence',
]


def load_manifest():
    """file_name -> cancer_type, built once at download time. No GDC call needed here anymore."""
    obj = s3.get_object(Bucket=BUCKET, Key=MANIFEST_KEY)
    df = pd.read_csv(io.BytesIO(obj['Body'].read()))
    return dict(zip(df['file_name'], df['cancer_type']))


def list_maf_files():
    paginator = s3.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=BUCKET, Prefix=RAW_PREFIX)
    files = []
    for page in pages:
        for obj in page.get('Contents', []):
            if obj['Key'].endswith('.maf.gz'):
                files.append(obj['Key'])
    return files


def extract_file_name(key):
    return key.split('/')[-1]


def process_maf(key, cancer_type):
    obj = s3.get_object(Bucket=BUCKET, Key=key)
    df = pd.read_csv(
        io.BytesIO(obj['Body'].read()),
        compression='gzip',
        sep='\t',
        comment='#',
        low_memory=False
    )

    if 'GDC_FILTER' in df.columns:
        df = df[df['GDC_FILTER'].isna()]
    if 'IMPACT' in df.columns:
        df = df[df['IMPACT'].isin(['HIGH', 'MODERATE'])]

    cols = [c for c in KEEP_COLS if c in df.columns]
    df = df[cols].copy()
    df = df.dropna(subset=['Hugo_Symbol', 'Tumor_Sample_Barcode'])
    df['cancer_type'] = cancer_type

    return df


# ---- MAIN ----
files = list_maf_files()
print(f"Found {len(files)} MAF files at s3://{BUCKET}/{RAW_PREFIX}")

if len(files) == 0:
    raise Exception("NO FILES FOUND — check your S3 prefix and bucket name")

manifest = load_manifest()
print(f"Loaded manifest with {len(manifest)} labeled files")

all_dfs = []
skipped = 0

for i, key in enumerate(files):
    file_name = extract_file_name(key)

    if file_name == 'manifest.csv':
        continue

    cancer_type = manifest.get(file_name)
    if cancer_type is None:
        skipped += 1
        continue

    try:
        df = process_maf(key, cancer_type)
        if len(df) > 0:
            all_dfs.append(df)
    except Exception as e:
        print(f"  ERROR on {key}: {e}")
        skipped += 1

    if (i + 1) % 50 == 0 or (i + 1) == len(files):
        print(f"  Processed {i+1}/{len(files)} files...")

print(f"\nFiles successfully processed: {len(all_dfs)} / {len(files)}  (skipped: {skipped})")

if len(all_dfs) == 0:
    raise Exception("all_dfs is empty — check logs above")

combined = pd.concat(all_dfs, ignore_index=True)
print(f"\nTotal combined rows: {combined.shape}")
print(f"Cancer type distribution:\n{combined['cancer_type'].value_counts()}")

buf = io.BytesIO()
combined.to_parquet(buf, index=False)
buf.seek(0)

s3.put_object(
    Bucket=BUCKET,
    Key=f'{OUTPUT_PREFIX}clean_mutations.parquet',
    Body=buf.getvalue()
)
print(f"\nDone. Saved to s3://{BUCKET}/{OUTPUT_PREFIX}clean_mutations.parquet")