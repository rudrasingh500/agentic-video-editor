"""
Cloud Run Jobs API client for video rendering.

This module provides functionality to:
- Create and deploy Cloud Run Jobs
- Execute jobs with parameter overrides
- Poll job execution status
- Handle job completion callbacks

Requires:
- google-cloud-run Python client
- Service account with Cloud Run Invoker permissions
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================


@dataclass
class CloudRunConfig:
    """Configuration for Cloud Run Jobs."""

    project_id: str
    region: str
    cpu_job_name: str = "video-render-cpu"
    gpu_job_name: str = "video-render-gpu"
    cpu_job_image: str = ""  # Set via environment
    gpu_job_image: str = ""  # Set via environment
    service_account_email: str = ""
    input_bucket: str = ""
    output_bucket: str = ""

    @classmethod
    def from_env(cls) -> CloudRunConfig:
        """Load configuration from environment variables."""
        return cls(
            project_id=os.getenv("GCP_PROJECT_ID", ""),
            region=os.getenv("GCP_REGION", "us-central1"),
            cpu_job_name=os.getenv("RENDER_CPU_JOB_NAME", "video-render-cpu"),
            gpu_job_name=os.getenv("RENDER_GPU_JOB_NAME", "video-render-gpu"),
            cpu_job_image=os.getenv("RENDER_CPU_IMAGE", ""),
            gpu_job_image=os.getenv("RENDER_GPU_IMAGE", ""),
            service_account_email=os.getenv("RENDER_SERVICE_ACCOUNT", ""),
            input_bucket=os.getenv("GCS_BUCKET", "video-editor"),
            output_bucket=os.getenv("GCS_RENDER_BUCKET", "video-editor-renders"),
        )


# =============================================================================
# DATA STRUCTURES
# =============================================================================


@dataclass
class JobExecution:
    """Represents a Cloud Run Job execution."""

    execution_id: str
    job_name: str
    status: str  # PENDING, RUNNING, SUCCEEDED, FAILED, CANCELLED
    create_time: str | None = None
    start_time: str | None = None
    completion_time: str | None = None
    error_message: str | None = None


@dataclass
class JobExecutionRequest:
    """Request to execute a Cloud Run Job."""

    job_id: str  # Our internal job ID
    manifest_gcs_path: str  # GCS path to render manifest JSON
    use_gpu: bool = False
    timeout_seconds: int = 3600  # 1 hour default
    memory: str = "32Gi"
    cpu: str = "8"


# =============================================================================
# CLOUD RUN JOBS CLIENT
# =============================================================================


class CloudRunJobsClient:
    """
    Client for managing Cloud Run Jobs for video rendering.

    This client handles:
    - Job execution with parameter overrides
    - Status polling
    - Error handling
    """

    def __init__(self, config: CloudRunConfig | None = None):
        self.config = config or CloudRunConfig.from_env()
        self._jobs_client = None
        self._executions_client = None
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Lazily initialize the Cloud Run clients."""
        if self._initialized:
            return

        try:
            from google.cloud import run_v2

            self._jobs_client = run_v2.JobsClient()
            self._executions_client = run_v2.ExecutionsClient()
            self._initialized = True
            logger.info("Cloud Run Jobs client initialized")
        except ImportError:
            logger.warning(
                "google-cloud-run not installed. "
                "Install with: pip install google-cloud-run"
            )
            self._jobs_client = None
            self._executions_client = None
        except Exception as e:
            logger.error(f"Failed to initialize Cloud Run client: {e}")
            self._jobs_client = None
            self._executions_client = None

    @property
    def is_available(self) -> bool:
        """Check if the Cloud Run client is available."""
        self._ensure_initialized()
        return self._jobs_client is not None

    def execute_render_job(self, request: JobExecutionRequest) -> JobExecution | None:
        """
        Execute a render job on Cloud Run.

        Args:
            request: Job execution parameters

        Returns:
            JobExecution with execution details, or None if failed
        """
        self._ensure_initialized()

        if not self._jobs_client:
            logger.error("Cloud Run client not available")
            return self._execute_local_fallback(request)

        try:
            from google.cloud import run_v2

            job_name = (
                self.config.gpu_job_name
                if request.use_gpu
                else self.config.cpu_job_name
            )
            full_job_name = (
                f"projects/{self.config.project_id}/"
                f"locations/{self.config.region}/"
                f"jobs/{job_name}"
            )

            # Create execution request with overrides
            run_request = run_v2.RunJobRequest(
                name=full_job_name,
                overrides=run_v2.RunJobRequest.Overrides(
                    container_overrides=[
                        run_v2.RunJobRequest.Overrides.ContainerOverride(
                            args=[
                                "--manifest",
                                request.manifest_gcs_path,
                                "--job-id",
                                request.job_id,
                            ],
                            env=[
                                run_v2.EnvVar(
                                    name="RENDER_JOB_ID", value=request.job_id
                                ),
                                run_v2.EnvVar(
                                    name="RENDER_MANIFEST",
                                    value=request.manifest_gcs_path,
                                ),
                            ],
                        )
                    ],
                    timeout=f"{request.timeout_seconds}s",
                ),
            )

            # Execute the job
            operation = self._jobs_client.run_job(request=run_request)
            execution = operation.result()

            return JobExecution(
                execution_id=execution.name.split("/")[-1],
                job_name=job_name,
                status="RUNNING",
                create_time=execution.create_time.isoformat()
                if execution.create_time
                else None,
                start_time=execution.start_time.isoformat()
                if execution.start_time
                else None,
            )

        except Exception as e:
            logger.error(f"Failed to execute Cloud Run job: {e}")
            return None

    def get_execution_status(
        self, job_name: str, execution_id: str
    ) -> JobExecution | None:
        """
        Get the status of a job execution.

        Args:
            job_name: Name of the Cloud Run job
            execution_id: Execution ID

        Returns:
            JobExecution with current status
        """
        self._ensure_initialized()

        if not self._executions_client:
            return None

        try:
            from google.cloud import run_v2

            full_name = (
                f"projects/{self.config.project_id}/"
                f"locations/{self.config.region}/"
                f"jobs/{job_name}/"
                f"executions/{execution_id}"
            )

            execution = self._executions_client.get_execution(
                request=run_v2.GetExecutionRequest(name=full_name)
            )

            # Map Cloud Run status to our status
            status = self._map_execution_status(execution)

            return JobExecution(
                execution_id=execution_id,
                job_name=job_name,
                status=status,
                create_time=execution.create_time.isoformat()
                if execution.create_time
                else None,
                start_time=execution.start_time.isoformat()
                if execution.start_time
                else None,
                completion_time=execution.completion_time.isoformat()
                if execution.completion_time
                else None,
                error_message=self._extract_error_message(execution),
            )

        except Exception as e:
            logger.error(f"Failed to get execution status: {e}")
            return None

    def cancel_execution(self, job_name: str, execution_id: str) -> bool:
        """
        Cancel a running job execution.

        Args:
            job_name: Name of the Cloud Run job
            execution_id: Execution ID

        Returns:
            True if cancelled successfully
        """
        self._ensure_initialized()

        if not self._executions_client:
            return False

        try:
            from google.cloud import run_v2

            full_name = (
                f"projects/{self.config.project_id}/"
                f"locations/{self.config.region}/"
                f"jobs/{job_name}/"
                f"executions/{execution_id}"
            )

            self._executions_client.delete_execution(
                request=run_v2.DeleteExecutionRequest(name=full_name)
            )
            return True

        except Exception as e:
            logger.error(f"Failed to cancel execution: {e}")
            return False

    def _map_execution_status(self, execution: Any) -> str:
        """Map Cloud Run execution status to our status enum."""
        # Cloud Run statuses:
        # - CONDITION_RECONCILING
        # - EXECUTION_CONDITION_ACTIVE
        # - CONDITION_SUCCEEDED
        # - CONDITION_FAILED

        if not execution.conditions:
            return "PENDING"

        for condition in execution.conditions:
            if condition.type == "Completed":
                if condition.state == "CONDITION_SUCCEEDED":
                    return "SUCCEEDED"
                elif condition.state == "CONDITION_FAILED":
                    return "FAILED"

        if execution.running_count > 0:
            return "RUNNING"

        return "PENDING"

    def _extract_error_message(self, execution: Any) -> str | None:
        """Extract error message from failed execution."""
        if not execution.conditions:
            return None

        for condition in execution.conditions:
            if condition.state == "CONDITION_FAILED" and condition.message:
                return condition.message

        return None

    def _execute_local_fallback(
        self, request: JobExecutionRequest
    ) -> JobExecution | None:
        """
        Fallback for local development without Cloud Run.

        In development, we can run the render job locally or skip it.
        """
        logger.warning(
            f"Cloud Run not available. "
            f"Render job {request.job_id} will need manual processing."
        )

        # Return a placeholder execution for tracking
        return JobExecution(
            execution_id=f"local-{request.job_id}",
            job_name="local",
            status="PENDING",
            error_message="Cloud Run not configured. Manual processing required.",
        )


# =============================================================================
# JOB DEFINITION MANAGEMENT
# =============================================================================


def create_cpu_job_definition(
    config: CloudRunConfig,
) -> dict[str, Any]:
    """
    Generate Cloud Run Job definition for CPU rendering.

    This can be used with gcloud or terraform to create the job.
    """
    return {
        "apiVersion": "run.googleapis.com/v1",
        "kind": "Job",
        "metadata": {
            "name": config.cpu_job_name,
            "annotations": {
                "run.googleapis.com/launch-stage": "BETA",
            },
        },
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "run.googleapis.com/execution-environment": "gen2",
                    }
                },
                "spec": {
                    "containers": [
                        {
                            "image": config.cpu_job_image,
                            "resources": {
                                "limits": {
                                    "cpu": "8",
                                    "memory": "32Gi",
                                }
                            },
                            "env": [
                                {"name": "GCS_BUCKET", "value": config.input_bucket},
                                {
                                    "name": "GCS_RENDER_BUCKET",
                                    "value": config.output_bucket,
                                },
                            ],
                            "volumeMounts": [
                                {"name": "input-volume", "mountPath": "/inputs"},
                                {"name": "output-volume", "mountPath": "/outputs"},
                            ],
                        }
                    ],
                    "volumes": [
                        {
                            "name": "input-volume",
                            "csi": {
                                "driver": "gcsfuse.run.googleapis.com",
                                "volumeAttributes": {
                                    "bucketName": config.input_bucket,
                                    "mountOptions": "implicit-dirs,only-dir=",
                                },
                                "readOnly": True,
                            },
                        },
                        {
                            "name": "output-volume",
                            "csi": {
                                "driver": "gcsfuse.run.googleapis.com",
                                "volumeAttributes": {
                                    "bucketName": config.output_bucket,
                                },
                            },
                        },
                    ],
                    "serviceAccountName": config.service_account_email,
                    "maxRetries": 1,
                    "timeoutSeconds": 3600,
                },
            }
        },
    }


def create_gpu_job_definition(
    config: CloudRunConfig,
) -> dict[str, Any]:
    """
    Generate Cloud Run Job definition for GPU rendering.

    This can be used with gcloud or terraform to create the job.
    """
    definition = create_cpu_job_definition(config)

    # Update for GPU
    definition["metadata"]["name"] = config.gpu_job_name
    definition["spec"]["template"]["metadata"]["annotations"].update(
        {
            "run.googleapis.com/gpu-type": "nvidia-l4",
            "run.googleapis.com/gpu-zonal-redundancy": "disabled",
        }
    )
    definition["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"][
        "nvidia.com/gpu"
    ] = "1"
    definition["spec"]["template"]["spec"]["containers"][0]["image"] = (
        config.gpu_job_image
    )

    return definition


def generate_gcloud_commands(config: CloudRunConfig) -> str:
    """
    Generate gcloud commands to create the render jobs.

    Useful for initial setup or CI/CD pipelines.
    """
    commands = []

    # CPU job
    commands.append(f"""
# Create CPU render job
gcloud run jobs create {config.cpu_job_name} \\
    --image {config.cpu_job_image} \\
    --region {config.region} \\
    --memory 32Gi \\
    --cpu 8 \\
    --max-retries 1 \\
    --task-timeout 3600 \\
    --service-account {config.service_account_email} \\
    --add-volume=name=input-volume,type=cloud-storage,bucket={config.input_bucket},readonly=true \\
    --add-volume-mount=volume=input-volume,mount-path=/inputs \\
    --add-volume=name=output-volume,type=cloud-storage,bucket={config.output_bucket} \\
    --add-volume-mount=volume=output-volume,mount-path=/outputs
""")

    # GPU job
    commands.append(f"""
# Create GPU render job
gcloud run jobs create {config.gpu_job_name} \\
    --image {config.gpu_job_image} \\
    --region {config.region} \\
    --memory 32Gi \\
    --cpu 8 \\
    --gpu 1 \\
    --gpu-type nvidia-l4 \\
    --no-gpu-zonal-redundancy \\
    --max-retries 1 \\
    --task-timeout 3600 \\
    --service-account {config.service_account_email} \\
    --add-volume=name=input-volume,type=cloud-storage,bucket={config.input_bucket},readonly=true \\
    --add-volume-mount=volume=input-volume,mount-path=/inputs \\
    --add-volume=name=output-volume,type=cloud-storage,bucket={config.output_bucket} \\
    --add-volume-mount=volume=output-volume,mount-path=/outputs
""")

    return "\n".join(commands)


# =============================================================================
# SINGLETON CLIENT
# =============================================================================


_client: CloudRunJobsClient | None = None


def get_cloud_run_client() -> CloudRunJobsClient:
    """Get the singleton Cloud Run Jobs client."""
    global _client
    if _client is None:
        _client = CloudRunJobsClient()
    return _client
