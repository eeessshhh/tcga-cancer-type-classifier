# Cancer Type Classifier

An end-to-end machine learning pipeline that classifies **5 cancer types** from MAF files (somatic mutation profiles), using open-source genomic data from TCGA.

Built using AWS tools (S3, Glue, Athena), trained with XGBoost and SHAP-based interpretability.

---

## Defining the problem

Each type of cancer causes a different impression in a patient's DNA. Some genes mutate more often in one cancer type than another. This project tries to answer the quesion: **given a patient's mutation profile, can a model accurately point out which cancer type they have?**

This is a mutation-based classification problem and it can support cancer of unknown primary (CUP) diagnoses (where the tumour site is ambiguous).

---

## Architecture

```
GDC API (TCGA open-access MAFs)
        │
        ▼
   S3: raw/tcga/
        │
        ▼
  AWS Glue (Python shell job)
  → filter PASS variants, clean MAF
        │
        ▼
   S3: processed/clean_maf/
        │
        ▼
  AWS Athena (SQL + CTAS)
  → top mutated genes per cancer type
        │
        ▼
   S3: processed/ml-ready/
        │
        ▼
  Local (Jupyter + XGBoost)
  → patient × gene binary matrix
  → per-cancer-type feature selection
  → train/test split (stratified 80/20)
        │
        ▼
   S3: models/xgboost-model/
        │
        ▼
  SHAP interpretability
  → beeswarm plots per cancer type
  → global gene importance chart
        │
        ▼
   S3: output/plots/ + output/predictions/
```

---

## Dataset

- **Source**: TCGA open-access masked somatic mutation data via GDC API
- **Cancer types**: BRCA (breast), COAD (colorectal), KIRC (kidney), LUAD (lung), PRAD (prostate)
- **Final matrix**: 473 patients × 363 genes (binary: 1 = gene mutated, 0 = not)
- **Feature selection**: Top 100 genes selected **per cancer type** (not globally) to avoid mutation burden bias — high-TMB cancers like COAD would otherwise dominate gene selection

---

## Results

| Metric | Score |
|--------|-------|
| Accuracy | 74% |
| Weighted F1 | 0.74 |

**Per-class F1:**

| Cancer type | F1 |
|-------------|-----|
| KIRC (kidney) | 0.86 |
| BRCA (breast) | 0.75 |
| COAD (colorectal) | 0.74 |
| LUAD (lung) | 0.72 |
| PRAD (prostate) | 0.65 |

KIRC is the easiest to classify. Its mutation profile (dominated by VHL and PBRM1) is highly identifiable. PRAD is the hardest to classify. Prostate cancer has a lower mutation rate and less obvious gene signals.

---

## Biological findings (SHAP)

SHAP values reveal which gene mutations drive each prediction — these align with known cancer biology:

- **KIRC**: VHL and PBRM1 are the dominant positive signals. Both are well-established tumour suppressor genes in clear cell renal carcinoma.
- **PRAD**: SPOP is the primary signal — consistent with its known role as the most commonly mutated gene in localised prostate cancer.
- **KIRC (negative)**: TP53 mutation is a strong *negative* signal for KIRC — TP53 mutations are common in many other cancers but rare in kidney clear cell, so their presence pushes the model *away* from a KIRC prediction.

---

## Tech stack

| Layer | Tools |
|-------|-------|
| Cloud storage | AWS S3 |
| ETL | AWS Glue (Python shell), pandas |
| SQL exploration | AWS Athena |
| ML training | XGBoost (local, SageMaker-compatible format) |
| Interpretability | SHAP |
| Orchestration | Jupyter notebooks |
| Infrastructure | boto3, IAM scoped user, SageMaker execution role |

---

## Repo structure

```
├── ingestion/
│   └── download_tcga_maf.py        # GDC API bulk download + S3 upload
├── transform/
│   ├── glue_clean_maf.py           # Glue job: filter + clean raw MAF files
│   ├── build_mutation_matrix.ipynb # Pivot to patient × gene binary matrix
│   └── feature_selection.ipynb     # Per-cancer-type top-100 gene selection
├── model/
│   ├── train_xgboost.ipynb         # XGBoost training + evaluation
│   └── shap_interpretability.ipynb # SHAP beeswarm plots + gene importance
├── output/
│   └── plots/                      # Confusion matrix, SHAP plots, gene chart
├── docs/
│   └── architecture.png
└── requirements.txt
```

---

## Methodological notes

- 14 patients (2.9% of 487) were excluded because their mutation profiles fell entirely outside the selected gene set. This is expected and explainable: these patients had very few mutations, none overlapping the top-100 gene lists for any cancer type.
- Feature selection used a per-cancer-type partitioned ranking rather than global mutation frequency. Global selection biases toward high tumour mutational burden (TMB) cancer types like COAD, underrepresenting low-TMB types like KIRC and PRAD.
- Model trained locally due to SageMaker instance service quota limitations on a new AWS account. Saved in SageMaker-compatible `.tar.gz` format for portability.

---

## Data access

Raw MAF files and processed matrices are stored in a private S3 bucket and are not included in this repo. All TCGA data used is open-access (no patient consent required) and available via the [GDC Data Portal](https://portal.gdc.cancer.gov/).