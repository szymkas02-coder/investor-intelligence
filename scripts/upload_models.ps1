# Upload retrained ML models to GCS so next Cloud Build deploy picks them up.
# Run this after retraining any model locally:
#   C:/Users/szymo/anaconda3/envs/geo/python.exe ml/regime.py train
#   ... (other models)
#   then: .\scripts\upload_models.ps1

$env:CLOUDSDK_PYTHON = "C:/Users/szymo/anaconda3/envs/geo/python.exe"

Write-Host "Uploading ML models to GCS..." -ForegroundColor Cyan

gcloud storage cp "d:\MOJE\DATA_SCIENCE\INVESTMENT_APP\investor_intelligence\models\*" `
    gs://investor-intelligence-496113-backup/models/ `
    --project investor-intelligence-496113

Write-Host "Done. Trigger a redeploy to pick up new models:" -ForegroundColor Green
Write-Host "  git commit --allow-empty -m 'redeploy: new ML models' && git push" -ForegroundColor Yellow
