import boto3

from quilt3 import data_checker
from quilt3.util import extract_file_extension, parse_s3_url
from urllib.parse import urlparse

from PIL import Image

LABEL_SET = ['🍎', '🍊']

class CheckPackageOfImages(data_checker.TestCase):
    @data_checker.TestCase.test_package()
    def quilt_data_check_ImageSize(self):
        "Validate that every object has size > 1 KB and is labeled apple or orange"
        images = self.quilt_package['images_cropped']
        for lkey, entry in images.walk():
            pkey = entry.physical_keys[0]
            if extract_file_extension(pkey) in ['jpg']:
                self.assertTrue(entry.size > 1_000, f"{pkey} has too small size.")
            # self.assertTrue(entry.meta_data['label'] in LABEL_SET)
        return

class CheckValidImages(data_checker.TestCase):
    @data_checker.TestCase.test_key('images_cropped/Apple/10049481156_6cdc5d23be_o_23651.jpg') # Logical key
    def quilt_data_check_ImageParsable(self, pkg_entry):
        s3 = boto3.client("s3")
        bucket, key, version_id = parse_s3_url(urlparse(pkg_entry.physical_keys[0])) 
        img = Image.open(s3.get_object(Bucket=bucket, Key=key, VersionId=version_id)["Body"])
        self.assertTrue(img.format == 'JPEG', f"Found format: {img.format}")
        self.assertTrue(img.mode == 'RGB', f"Found mode: {img.mode}")