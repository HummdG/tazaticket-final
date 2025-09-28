"""
Secure S3 Handler using Presigned URLs for TazaTicket
"""
import os
import hashlib
import asyncio
import aiohttp
import aioboto3
from datetime import datetime, timedelta
from typing import Optional
from botocore.exceptions import ClientError, NoCredentialsError


class SecureTazaTicketS3Handler:
    """Secure voice file handling with presigned URLs"""

    def __init__(self):
        self.bucket_name = "tazaticket"
        self.region = "eu-north-1"

        if self._has_credentials():
            try:
                _ = aioboto3.Session()
                print("✅ Secure7 TazaTicket S3 client ready (using aioboto3)")
            except Exception as e:
                print(f"❌ Failed to initialize S3 client: {e}")

    def _has_credentials(self) -> bool:
        return all(
            [
                os.getenv("AWS_ACCESS_KEY_ID"),
                os.getenv("AWS_SECRET_ACCESS_KEY"),
            ]
        )

    def _require_client(self):
        if not self._has_credentials():
            raise RuntimeError(
                "❌ S3 client is not initialized. Check your AWS credentials and configuration."
            )
        try:
            import aioboto3
            _ = aioboto3.Session()
        except ImportError:
            raise RuntimeError("❌ aioboto3 is not installed or available")

    def _get_s3_client(self):
        """Centralized async S3 client getter"""
        self._require_client()
        session = aioboto3.Session(
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        )
        return session.client("s3", region_name=self.region)

    async def upload_from_twilio_url(self, media_url: str, user_id: str) -> Optional[str]:
        """Download from Twilio authenticated URL and upload to S3 with public access for AssemblyAI"""
        if not self.is_configured():
            print("❌ Secure S3 not configured or client not initialized")
            return None

        try:
            account_sid = os.getenv("TWILIO_ACCOUNT_SID")
            auth_token = os.getenv("TWILIO_AUTH_TOKEN")

            if not account_sid or not auth_token:
                print("❌ Twilio credentials not found in environment variables")
                return None

            print("🔐 Downloading Twilio media for S3 upload...")

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    media_url,
                    auth=aiohttp.BasicAuth(account_sid, auth_token),
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    response.raise_for_status()
                    content = await response.read()

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_hash = hashlib.md5(media_url.encode()).hexdigest()[:8]
            filename = f"assemblyai-temp/{user_id}/{timestamp}_{file_hash}.ogg"

            print(f"📤 Uploading to S3: {filename}")

            async with self._get_s3_client() as client:
                await client.put_object(
                    Bucket=self.bucket_name,
                    Key=filename,
                    Body=content,
                    ContentType="audio/ogg",
                    CacheControl="max-age=3600",
                    Metadata={
                        "user-id": user_id,
                        "created-at": datetime.now().isoformat(),
                        "service": "tazaticket-assemblyai",
                        "type": "voice-input",
                        "source": "twilio",
                    },
                )

                public_url = await client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket_name, "Key": filename},
                    ExpiresIn=3600,
                )
                print(f"✅ Presigned URL created for AssemblyAI: {public_url[:50]}...")

                await self._set_cleanup_tags_temp(filename)

            return public_url

        except Exception as e:
            print(f"❌ Error uploading from Twilio URL: {e}")
            return None

    async def upload_voice_file(self, local_file_path: str, user_id: str) -> Optional[str]:
        """Upload voice file and return secure presigned URL"""
        if not self.is_configured():
            print("❌ Secure S3 not configured or client not initialized")
            return None
        if not os.path.exists(local_file_path):
            print(f"❌ Local file not found: {local_file_path}")
            return None

        try:
            self._require_client()

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_hash = await asyncio.to_thread(
                self._generate_file_hash, local_file_path
            )
            file_hash = file_hash[:8]
            file_extension = os.path.splitext(local_file_path)[1] or ".mp3"
            filename = f"voice/{user_id}/{timestamp}_{file_hash}{file_extension}"
            print(f"🔒 Uploading to secure TazaTicket S3: {filename}")

            async with self._get_s3_client() as client:
                # Use streaming upload (better than reading full file in memory)
                def open_file():
                    return open(local_file_path, "rb")

                with await asyncio.to_thread(open_file) as fp:
                    await client.upload_fileobj(
                        fp,
                        self.bucket_name,
                        filename,
                        ExtraArgs={
                            "ContentType": "audio/mpeg",
                            "CacheControl": "max-age=3600",
                            "Metadata": {
                                "user-id": user_id,
                                "created-at": datetime.now().isoformat(),
                                "service": "tazaticket-whatsapp-bot",
                                "type": "voice-response",
                            },
                        },
                    )

                presigned_url = await client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket_name, "Key": filename},
                    ExpiresIn=7200,
                )
                print(
                    f"✅ Secure presigned URL created (expires in 2h): {presigned_url[:50]}..."
                )

                await self._set_cleanup_tags(filename)

                return presigned_url
        except NoCredentialsError:
            print("❌ AWS credentials not found")
            return None
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
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
            h = hashlib.md5()
            with open(file_path, "rb") as f:
                while chunk := f.read(8192):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return hashlib.md5(str(datetime.now()).encode()).hexdigest()

    async def _set_cleanup_tags(self, filename: str):
        """Set tags for automatic cleanup"""
        try:
            async with self._get_s3_client() as client:
                await client.put_object_tagging(
                    Bucket=self.bucket_name,
                    Key=filename,
                    Tagging={
                        "TagSet": [
                            {"Key": "Service", "Value": "TazaTicket"},
                            {"Key": "Type", "Value": "VoiceMessage"},
                            {"Key": "AutoDelete", "Value": "true"},
                            {
                                "Key": "ExpiryDate",
                                "Value": (
                                    datetime.now() + timedelta(days=1)
                                ).strftime("%Y-%m-%d"),
                            },
                        ]
                    },
                )
        except RuntimeError as e:
            print(str(e))
        except Exception as e:
            print(f"⚠️ Could not set cleanup tags: {e}")

    async def _set_cleanup_tags_temp(self, filename: str):
        """Set tags for automatic cleanup of temporary files (shorter expiry)"""
        try:
            async with self._get_s3_client() as client:
                await client.put_object_tagging(
                    Bucket=self.bucket_name,
                    Key=filename,
                    Tagging={
                        "TagSet": [
                            {"Key": "Service", "Value": "TazaTicket"},
                            {"Key": "Type", "Value": "TempVoiceInput"},
                            {"Key": "AutoDelete", "Value": "true"},
                            {
                                "Key": "ExpiryDate",
                                "Value": (
                                    datetime.now() + timedelta(hours=6)
                                ).strftime("%Y-%m-%d"),
                            },
                        ]
                    },
                )
        except RuntimeError as e:
            print(str(e))
        except Exception as e:
            print(f"⚠️ Could not set cleanup tags: {e}")

    async def delete_voice_file(self, s3_key: str) -> bool:
        """Delete voice file from S3"""
        try:
            async with self._get_s3_client() as client:
                await client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            print(f"🗑️ Deleted voice file: {s3_key}")
            return True
        except RuntimeError as e:
            print(str(e))
            return False
        except Exception as e:
            print(f"❌ Failed to delete file: {e}")
            return False

    async def test_connection(self) -> dict:
        """Test secure connection"""
        if not self.is_configured():
            return {"success": False, "error": "Not configured or client not initialized"}
        try:
            test_key = "voice/test/secure_test.txt"
            test_content = f"Secure TazaTicket test: {datetime.now()}"

            async with self._get_s3_client() as client:
                await client.head_bucket(Bucket=self.bucket_name)

                await client.put_object(
                    Bucket=self.bucket_name,
                    Key=test_key,
                    Body=test_content,
                    ContentType="text/plain",
                )

                presigned_url = await client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket_name, "Key": test_key},
                    ExpiresIn=300,
                )

                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        presigned_url, timeout=aiohttp.ClientTimeout(total=10)
                    ) as response:
                        response.raise_for_status()

                await client.delete_object(Bucket=self.bucket_name, Key=test_key)

            return {
                "success": True,
                "message": "Secure TazaTicket S3 working perfectly!",
                "bucket": self.bucket_name,
                "region": self.region,
                "security": "Private bucket with presigned URLs",
            }
        except RuntimeError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def is_configured(self) -> bool:
        """Check if secure S3 is configured"""
        return self._has_credentials()


# Global secure TazaTicket S3 handler
secure_tazaticket_s3 = SecureTazaTicketS3Handler()
