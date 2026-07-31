import boto3
from botocore.config import Config

s3 = boto3.client('s3',
    endpoint_url='https://222ffe916db1155102a45e4cfb4a4ec8.r2.cloudflarestorage.com',
    aws_access_key_id='0ac626019adf6daa0130fd49c9ca0922',
    aws_secret_access_key='b00c99c3612acf4f89aa723308c5f463d9bf6b49543f86cea6e3ab5fce59b0fd',
    config=Config(signature_version='s3v4'),
    region_name='auto'
)

try:
    response = s3.list_buckets()
    print("Buckets:")
    for bucket in response['Buckets']:
        print(f" - {bucket['Name']}")
except Exception as e:
    print(f"ListBuckets failed: {e}")
