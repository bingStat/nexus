"""Sync canonical Nexus public documents to Cloudflare R2."""
import os
from pathlib import Path
import boto3
from botocore.config import Config
required=("R2_ENDPOINT_URL","R2_ACCESS_KEY_ID","R2_SECRET_ACCESS_KEY")
missing=[n for n in required if not os.environ.get(n)]
if missing: raise SystemExit("Missing environment variables: "+", ".join(missing))
root=Path(__file__).resolve().parents[1]
s3=boto3.client("s3",endpoint_url=os.environ["R2_ENDPOINT_URL"],aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],config=Config(signature_version="s3v4"),region_name="auto")
bucket=os.environ.get("R2_BUCKET","nexus")
for path,key,ctype in ((root/"nexus_system_prompt.md","nexus_system_prompt.md","text/markdown; charset=utf-8"),(root/"README.md","README.md","text/markdown; charset=utf-8")):
    s3.upload_file(str(path),bucket,key,ExtraArgs={"ContentType":ctype,"CacheControl":"no-cache"})
    print(f"[OK] {path.name} -> r2://{bucket}/{key}")
