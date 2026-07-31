import boto3
from botocore.config import Config

s3 = boto3.client('s3',
    endpoint_url='https://222ffe916db1155102a45e4cfb4a4ec8.r2.cloudflarestorage.com',
    aws_access_key_id='0ac626019adf6daa0130fd49c9ca0922',
    aws_secret_access_key='b00c99c3612acf4f89aa723308c5f463d9bf6b49543f86cea6e3ab5fce59b0fd',
    config=Config(signature_version='s3v4'),
    region_name='auto'
)

source_file = r"C:\Users\Bing\.gemini\antigravity-cli\brain\0517fc54-ebfb-495d-a2d3-64901aa216f4\nexus_dashboard.html"

try:
    s3.upload_file(
        source_file, 
        "nexus", 
        "index.html", 
        ExtraArgs={'ContentType': 'text/html; charset=utf-8', 'CacheControl': 'no-cache'}
    )
    print("SUCCESS")
except Exception as e:
    print(f"FAILED: {e}")

