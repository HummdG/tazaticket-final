"""
Secure S3 Handler using Presigned URLs for TazaTicket
"""
import os
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from datetime import datetime, timedelta
from typing import Optional
import hashlib

class SecureTazaTicketS3Handler:
    """Secure voice file handling with presigned URLs"""
    
    def __init__(self):
        self.bucket_name = "tazaticket"
        self.region = "eu-north-1"
        self.s3_client = None
        
        if self._has_credentials():
            try:
                self.s3_client = boto3.client(
                    's3',
                    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
                    region_name=self.region
                )
                print(f"✅ Secure TazaTicket S3 client initialized")
            except Exception as e:
                print(f"❌ Failed to initialize S3 client: {e}")
                self.s3_client = None
    
    def _has_credentials(self) -> bool:
        return all([
            os.getenv('AWS_ACCESS_KEY_ID'),
            os.getenv('AWS_SECRET_ACCESS_KEY')
        ])
    
    def _require_client(self):
        if self.s3_client is None:
            raise RuntimeError("❌ S3 client is not initialized. Check your AWS credentials and configuration.")
    
    def upload_from_twilio_url(self, media_url: str, user_id: str) -> Optional[str]:
        """Download from Twilio authenticated URL and upload to S3 with public access for AssemblyAI"""
        if not self.is_configured():
            print("❌ Secure S3 not configured or client not initialized")
            return None
            
        try:
            import requests
            import tempfile
            
            # Get Twilio credentials from environment
            account_sid = os.getenv('TWILIO_ACCOUNT_SID')
            auth_token = os.getenv('TWILIO_AUTH_TOKEN')
            
            if not account_sid or not auth_token:
                print("❌ Twilio credentials not found in environment variables")
                return None
            
            print(f"🔐 Downloading Twilio media for S3 upload...")
            
            # Download from Twilio with authentication
            response = requests.get(
                media_url, 
                auth=(account_sid, auth_token),
                timeout=30,
                stream=True
            )
            response.raise_for_status()
            
            # Generate unique filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_hash = hashlib.md5(media_url.encode()).hexdigest()[:8]
            filename = f"assemblyai-temp/{user_id}/{timestamp}_{file_hash}.ogg"
            
            print(f"📤 Uploading to S3: {filename}")
            
            # Upload directly from stream to S3 (without ACL)
            self.s3_client.upload_fileobj(
                response.raw,
                self.bucket_name,
                filename,
                ExtraArgs={
                    'ContentType': 'audio/ogg',
                    'CacheControl': 'max-age=3600',
                    'Metadata': {
                        'user-id': user_id,
                        'created-at': datetime.now().isoformat(),
                        'service': 'tazaticket-assemblyai',
                        'type': 'voice-input',
                        'source': 'twilio'
                    }
                }
            )
            
            # Generate presigned URL for public access (longer expiry for AssemblyAI processing)
            public_url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': filename},
                ExpiresIn=3600  # 1 hour should be enough for AssemblyAI to process
            )
            print(f"✅ Presigned URL created for AssemblyAI: {public_url[:50]}...")
            
            # Set tags for cleanup (shorter expiry for temp files)
            self._set_cleanup_tags_temp(filename)
            
            return public_url
            
        except Exception as e:
            print(f"❌ Error uploading from Twilio URL: {e}")
            return None

    def upload_voice_file(self, local_file_path: str, user_id: str) -> Optional[str]:
        """Upload voice file and return secure presigned URL"""
        if not self.is_configured():
            print("❌ Secure S3 not configured or client not initialized")
            return None
        if not os.path.exists(local_file_path):
            print(f"❌ Local file not found: {local_file_path}")
            return None
        try:
            self._require_client()
            # Generate unique filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_hash = self._generate_file_hash(local_file_path)[:8]
            file_extension = os.path.splitext(local_file_path)[1] or '.mp3'
            filename = f"voice/{user_id}/{timestamp}_{file_hash}{file_extension}"
            print(f"🔒 Uploading to secure TazaTicket S3: {filename}")
            # Upload file (stays private)
            self.s3_client.upload_file(
                local_file_path,
                self.bucket_name,
                filename,
                ExtraArgs={
                    'ContentType': 'audio/mpeg',
                    'CacheControl': 'max-age=3600',
                    'Metadata': {
                        'user-id': user_id,
                        'created-at': datetime.now().isoformat(),
                        'service': 'tazaticket-whatsapp-bot',
                        'type': 'voice-response'
                    }
                }
            )
            # Generate presigned URL (expires in 2 hours)
            presigned_url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': filename},
                ExpiresIn=7200  # 2 hours (7200 seconds)
            )
            print(f"✅ Secure presigned URL created (expires in 2h): {presigned_url[:50]}...")
            # Set tags for cleanup
            self._set_cleanup_tags(filename)
            return presigned_url
        except NoCredentialsError:
            print("❌ AWS credentials not found")
            return None
        except ClientError as e:
            error_code = e.response['Error']['Code']
            print(f"❌ S3 error [{error_code}]: {e.response['Error']['Message']}")
            return None
        except RuntimeError as e:
            print(str(e))
            return None
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            return None
    
    def _generate_file_hash(self, file_path: str) -> str:
        """Generate hash for unique file naming"""
        try:
            with open(file_path, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception:
            return hashlib.md5(str(datetime.now()).encode()).hexdigest()
    
    def _set_cleanup_tags(self, filename: str):
        """Set tags for automatic cleanup"""
        try:
            self._require_client()
            self.s3_client.put_object_tagging(
                Bucket=self.bucket_name,
                Key=filename,
                Tagging={
                    'TagSet': [
                        {'Key': 'Service', 'Value': 'TazaTicket'},
                        {'Key': 'Type', 'Value': 'VoiceMessage'},
                        {'Key': 'AutoDelete', 'Value': 'true'},
                        {'Key': 'ExpiryDate', 'Value': (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')}
                    ]
                }
            )
        except RuntimeError as e:
            print(str(e))
        except Exception as e:
            print(f"⚠️ Could not set cleanup tags: {e}")

    def _set_cleanup_tags_temp(self, filename: str):
        """Set tags for automatic cleanup of temporary files (shorter expiry)"""
        try:
            self._require_client()
            self.s3_client.put_object_tagging(
                Bucket=self.bucket_name,
                Key=filename,
                Tagging={
                    'TagSet': [
                        {'Key': 'Service', 'Value': 'TazaTicket'},
                        {'Key': 'Type', 'Value': 'TempVoiceInput'},
                        {'Key': 'AutoDelete', 'Value': 'true'},
                        {'Key': 'ExpiryDate', 'Value': (datetime.now() + timedelta(hours=6)).strftime('%Y-%m-%d')}  # 6 hours for temp files
                    ]
                }
            )
        except RuntimeError as e:
            print(str(e))
        except Exception as e:
            print(f"⚠️ Could not set cleanup tags: {e}")
    
    def delete_voice_file(self, s3_key: str) -> bool:
        """Delete voice file from S3"""
        try:
            self._require_client()
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            print(f"🗑️ Deleted voice file: {s3_key}")
            return True
        except RuntimeError as e:
            print(str(e))
            return False
        except Exception as e:
            print(f"❌ Failed to delete file: {e}")
            return False
    
    def test_connection(self) -> dict:
        """Test secure connection"""
        if not self.is_configured():
            return {"success": False, "error": "Not configured or client not initialized"}
        try:
            self._require_client()
            # Test bucket access
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            # Test upload and presigned URL generation
            test_key = "voice/test/secure_test.txt"
            test_content = f"Secure TazaTicket test: {datetime.now()}"
            # Upload test file
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=test_key,
                Body=test_content,
                ContentType='text/plain'
            )
            # Generate presigned URL
            presigned_url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': test_key},
                ExpiresIn=300  # 5 minutes for test
            )
            # Test the presigned URL works
            import requests
            response = requests.get(presigned_url, timeout=10)
            response.raise_for_status()
            # Cleanup
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=test_key)
            return {
                "success": True,
                "message": "Secure TazaTicket S3 working perfectly!",
                "bucket": self.bucket_name,
                "region": self.region,
                "security": "Private bucket with presigned URLs"
            }
        except RuntimeError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def is_configured(self) -> bool:
        """Check if secure S3 is configured"""
        return all([
            self._has_credentials(),
            self.s3_client is not None
        ])

# Global secure TazaTicket S3 handler
secure_tazaticket_s3 = SecureTazaTicketS3Handler() 