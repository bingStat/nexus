"""sync_r2.py - Sync Nexus documentation to R2 bucket (nexus.bings.app)"""
import boto3
from botocore.config import Config

s3 = boto3.client(
    's3',
    endpoint_url='https://222ffe916db1155102a45e4cfb4a4ec8.r2.cloudflarestorage.com',
    aws_access_key_id='0ac626019adf6daa0130fd49c9ca0922',
    aws_secret_access_key='b00c99c3612acf4f89aa723308c5f463d9bf6b49543f86cea6e3ab5fce59b0fd',
    config=Config(signature_version='s3v4'),
    region_name='auto'
)

BUCKET = 'nexus'
REPO_ROOT = r'C:\Users\Bing\aurora\Workstation\Nexus'

files = [
    ('nexus_system_prompt.md',  'nexus_system_prompt.md',  'text/markdown; charset=utf-8'),
    ('nexus_openapi.json',      'nexus_openapi.json',       'application/json; charset=utf-8'),
    ('README.md',               'README.md',                'text/markdown; charset=utf-8'),
]

for local_name, r2_key, content_type in files:
    local_path = REPO_ROOT + '\\' + local_name
    try:
        s3.upload_file(
            local_path, BUCKET, r2_key,
            ExtraArgs={'ContentType': content_type, 'CacheControl': 'no-cache'}
        )
        print(f'[OK] {local_name} -> r2://{BUCKET}/{r2_key}')
    except Exception as e:
        print(f'[FAIL] {local_name}: {e}')

print('\nBucket contents:')
resp = s3.list_objects_v2(Bucket=BUCKET)
for obj in resp.get('Contents', []):
    key = obj['Key']
    size = obj['Size']
    print(f'  {key} ({size} bytes)')
