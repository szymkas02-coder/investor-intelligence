from google.cloud import storage
import pathlib

models_dir = pathlib.Path("/app/models")
models_dir.mkdir(exist_ok=True)

bucket = storage.Client(project="investor-intelligence-496113").bucket("investor-intelligence-496113-backup")
for blob in bucket.list_blobs(prefix="models/"):
    fname = blob.name.split("/", 1)[1]
    if fname:
        dest = models_dir / fname
        blob.download_to_filename(str(dest))
        print(f"Downloaded {fname}")
