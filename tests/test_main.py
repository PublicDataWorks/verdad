import sys
from unittest.mock import call, patch, Mock
import pytest

class TestMain:
    @pytest.fixture(autouse=True)
    def setup_module(self):
        """Setup and cleanup for each test"""
        # Remove main module if it exists
        if 'main' in sys.modules:
            del sys.modules['main']
        yield
        # Cleanup after test
        if 'main' in sys.modules:
            del sys.modules['main']

    @pytest.fixture
    def mock_environment(self):
        """Setup test environment variables"""
        env_vars = {
            "SENTRY_DSN": "https://test@test.ingest.sentry.io/123456",
            "R2_BUCKET_NAME": "test-bucket",
            "R2_ENDPOINT_URL": "https://test.r2.endpoint",
            "R2_ACCESS_KEY_ID": "test-access-key",
            "R2_SECRET_ACCESS_KEY": "test-secret-key",
            "GOOGLE_GEMINI_KEY": "test-gemini-key",
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_KEY": "test-supabase-key"
        }
        with patch.dict('os.environ', env_vars, clear=True):
            yield env_vars

    def test_client_initialization(self, mock_environment):
        """Test client initialization"""
        with patch('sentry_sdk.init') as mock_sentry, \
             patch('boto3.client') as mock_boto3, \
             patch('processing_pipeline.supabase_utils.SupabaseClient') as mock_supabase, \
             patch('dotenv.load_dotenv'):

            import main

            # Verify Sentry initialization
            mock_sentry.assert_called_once_with(dsn=mock_environment["SENTRY_DSN"])

            # Verify boto3 client initialization
            mock_boto3.assert_called_once_with(
                "s3",
                endpoint_url=mock_environment["R2_ENDPOINT_URL"],
                aws_access_key_id=mock_environment["R2_ACCESS_KEY_ID"],
                aws_secret_access_key=mock_environment["R2_SECRET_ACCESS_KEY"]
            )

            # Verify Supabase client initialization
            mock_supabase.assert_called_once_with(
                supabase_url=mock_environment["SUPABASE_URL"],
                supabase_key=mock_environment["SUPABASE_KEY"]
            )

    def test_main_execution_success(self, mock_environment):
        """Test successful main execution path"""
        with patch('sentry_sdk.init'), \
             patch('boto3.client') as mock_boto3, \
             patch('processing_pipeline.supabase_utils.SupabaseClient'), \
             patch('processing_pipeline.timestamped_transcription_generator.TimestampedTranscriptionGenerator') as mock_generator, \
             patch('os.path.exists', return_value=True), \
             patch('os.remove') as mock_remove, \
             patch('builtins.print') as mock_print, \
             patch('dotenv.load_dotenv'):

            # Setup mock returns
            mock_s3 = Mock()
            mock_boto3.return_value = mock_s3
            mock_generator.run.return_value = "Test transcription result"

            # Import and run main
            import main
            main.main()

            # Verify S3 download
            mock_s3.download_file.assert_called_once_with(
                mock_environment["R2_BUCKET_NAME"],
                "radio_1853b3/radio_1853b3_20241127_102353.mp3",
                "radio_1853b3_20241127_102353.mp3"
            )

            # Verify transcription generation
            mock_generator.run.assert_called_once_with(
                "radio_1853b3_20241127_102353.mp3",
                mock_environment["GOOGLE_GEMINI_KEY"],
                10
            )
            mock_print.assert_called_with("Test transcription result")
            mock_remove.assert_called_once_with("radio_1853b3_20241127_102353.mp3")

    def test_main_execution_file_not_found(self, mock_environment):
        """Test main execution when file doesn't exist"""
        with patch('sentry_sdk.init'), \
            patch('boto3.client') as mock_boto3, \
            patch('processing_pipeline.supabase_utils.SupabaseClient'), \
            patch('os.path.exists', return_value=False) as mock_exists, \
            patch('os.remove') as mock_remove, \
            patch('builtins.print') as mock_print, \
            patch('dotenv.load_dotenv'):

            mock_s3 = Mock()
            mock_boto3.return_value = mock_s3

            # Import and run main
            import main
            main.main()

            # Verify download was attempted
            mock_s3.download_file.assert_called_once_with(
                mock_environment["R2_BUCKET_NAME"],
                "radio_1853b3/radio_1853b3_20241127_102353.mp3",
                "radio_1853b3_20241127_102353.mp3"
            )

            # Verify existence checks
            assert mock_exists.call_count == 2  # Once for main check, once for cleanup
            mock_exists.assert_has_calls([
                call("radio_1853b3_20241127_102353.mp3"),
                call("radio_1853b3_20241127_102353.mp3")
            ])

            # Verify output
            mock_print.assert_called_with("File radio_1853b3_20241127_102353.mp3 does not exist")

            # Verify no removal attempt was made
            mock_remove.assert_not_called()

    def test_main_execution_with_download_error(self, mock_environment):
        """Test main execution when S3 download fails"""
        with patch('sentry_sdk.init'), \
            patch('boto3.client') as mock_boto3, \
            patch('processing_pipeline.supabase_utils.SupabaseClient'), \
            patch('os.path.exists', return_value=False) as mock_exists, \
            patch('os.remove') as mock_remove, \
            patch('dotenv.load_dotenv'):

            mock_s3 = Mock()
            mock_s3.download_file.side_effect = Exception("Download failed")
            mock_boto3.return_value = mock_s3

            # Import and run main
            import main
            with pytest.raises(Exception, match="Download failed"):
                main.main()

            # Verify existence check was made
            mock_exists.assert_called_with("radio_1853b3_20241127_102353.mp3")
            # Since file doesn't exist, remove should not be called
            mock_remove.assert_not_called()

    def test_main_execution_with_transcription_error(self, mock_environment):
        """Test main execution when transcription generation fails"""
        with patch('sentry_sdk.init'), \
             patch('boto3.client') as mock_boto3, \
             patch('processing_pipeline.supabase_utils.SupabaseClient'), \
             patch('processing_pipeline.timestamped_transcription_generator.TimestampedTranscriptionGenerator') as mock_generator, \
             patch('os.path.exists', return_value=True), \
             patch('os.remove') as mock_remove, \
             patch('dotenv.load_dotenv'):

            mock_s3 = Mock()
            mock_boto3.return_value = mock_s3
            mock_generator.run.side_effect = Exception("Transcription failed")

            # Import and run main
            import main
            with pytest.raises(Exception, match="Transcription failed"):
                main.main()

            mock_remove.assert_called_once_with("radio_1853b3_20241127_102353.mp3")

    def test_main_execution_with_cleanup_error(self, mock_environment):
        """Test main execution when cleanup fails"""
        with patch('sentry_sdk.init'), \
             patch('boto3.client') as mock_boto3, \
             patch('processing_pipeline.supabase_utils.SupabaseClient'), \
             patch('processing_pipeline.timestamped_transcription_generator.TimestampedTranscriptionGenerator') as mock_generator, \
             patch('os.path.exists', return_value=True), \
             patch('os.remove', side_effect=Exception("Cleanup failed")) as mock_remove, \
             patch('builtins.print') as mock_print, \
             patch('dotenv.load_dotenv'):

            mock_s3 = Mock()
            mock_boto3.return_value = mock_s3
            mock_generator.run.return_value = "Test transcription result"

            # Import and run main
            import main
            with pytest.raises(Exception, match="Cleanup failed"):
                main.main()

            mock_remove.assert_called_once_with("radio_1853b3_20241127_102353.mp3")
