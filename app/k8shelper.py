"""Create/delete Sandbox CRs (agents.x-k8s.io/v1alpha1) for each task.

v0.4.6 schema: spec.podTemplate (full PodSpec) + spec.volumeClaimTemplates + spec.service.
Cap with activeDeadlineSeconds and self-delete on completion.
"""
import base64
import json

from kubernetes import client, config

from .common import env, get_logger

log = get_logger("k8s")

GROUP = "agents.x-k8s.io"
VERSION = "v1alpha1"
PLURAL = "sandboxes"
NS = env("SANDBOX_NAMESPACE", "agent-sandbox")
IMAGE = env("SANDBOX_IMAGE", "ghcr.io/duyetbot/claude-agent-runner:latest")
IMAGE_PULL_POLICY = env("SANDBOX_IMAGE_PULL_POLICY", "Always")
CPU_REQUEST = env("SANDBOX_CPU_REQUEST", "200m")
MEM_REQUEST = env("SANDBOX_MEM_REQUEST", "512Mi")
SERVICE_ACCOUNT = env("SANDBOX_SERVICE_ACCOUNT", "claude-agent-runner")
RUN_AS_USER = int(env("SANDBOX_RUN_AS_USER", "1000"))
RUN_AS_GROUP = int(env("SANDBOX_RUN_AS_GROUP", "1000"))
RESTART_POLICY = env("SANDBOX_RESTART_POLICY", "Never")
CONTAINER_NAME = env("SANDBOX_CONTAINER_NAME", "agent")
CONTAINER_COMMAND = env("SANDBOX_CONTAINER_COMMAND", "python -m app.agent")
CONTAINER_WORKDIR = env("SANDBOX_CONTAINER_WORKDIR", "/workspace")
SECRET_REF_NAME = env("SANDBOX_SECRET_REF", "claude-agent-runner-secret")
CONFIGMAP_REF_NAME = env("SANDBOX_CONFIGMAP_REF", "claude-agent-runner-config")
PVC_ACCESS_MODE = env("SANDBOX_PVC_ACCESS_MODE", "ReadWriteOnce")
APP_LABEL = env("SANDBOX_APP_LABEL", "claude-agent-runner")


def _api() -> client.CustomObjectsApi:
    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()
    return client.CustomObjectsApi()


def _pod_template(task: dict, task_b64: str) -> dict:
    return {
        "metadata": {"labels": {"app": APP_LABEL}},
        "spec": {
            "restartPolicy": RESTART_POLICY,
            "serviceAccountName": SERVICE_ACCOUNT,
            "activeDeadlineSeconds": int(env("SANDBOX_DEADLINE_SECONDS", "1200")),
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": RUN_AS_USER,
                "fsGroup": RUN_AS_GROUP,
            },
            "containers": [{
                "name": CONTAINER_NAME,
                "image": IMAGE,
                "imagePullPolicy": IMAGE_PULL_POLICY,
                "command": CONTAINER_COMMAND.split(),
                "workingDir": CONTAINER_WORKDIR,
                "envFrom": [
                    {"secretRef": {"name": SECRET_REF_NAME}},
                    {"configMapRef": {"name": CONFIGMAP_REF_NAME}},
                ],
                "env": [
                    {"name": "TASK_JSON", "value": task_b64},
                    {"name": "HOME", "value": "/home/agent"},
                    {"name": "PYTHONUNBUFFERED", "value": "1"},
                ],
                "securityContext": {
                    "allowPrivilegeEscalation": False,
                    "readOnlyRootFilesystem": True,
                    "capabilities": {"drop": ["ALL"]},
                },
                "volumeMounts": [
                    {"name": "workspace", "mountPath": "/workspace"},
                    {"name": "tmp", "mountPath": "/tmp"},
                    {"name": "home", "mountPath": "/home/agent"},
                ],
                "resources": {
                    "requests": {"cpu": CPU_REQUEST, "memory": MEM_REQUEST},
                    "limits": {
                        "cpu": env("SANDBOX_CPU_LIMIT", "1000m"),
                        "memory": env("SANDBOX_MEM_LIMIT", "2Gi"),
                    },
                },
            }],
            "volumes": [
                {"name": "tmp", "emptyDir": {}},
                {"name": "home", "emptyDir": {}},
            ],
        },
    }


def create_sandbox(task: dict) -> str:
    name = task["sandbox_name"]
    task_b64 = base64.b64encode(json.dumps(task).encode()).decode()
    body = {
        "apiVersion": f"{GROUP}/{VERSION}",
        "kind": "Sandbox",
        "metadata": {
            "name": name,
            "labels": {"app": APP_LABEL},
            "annotations": {
                "agent-runner/repo": task.get("repo_full", ""),
                "agent-runner/issue": str(task.get("number", "")),
                "agent-runner/reason": task.get("reason", ""),
            },
        },
        "spec": {
            "podTemplate": _pod_template(task, task_b64),
            "volumeClaimTemplates": [{
                "metadata": {"name": "workspace"},
                "spec": {
                    "accessModes": [PVC_ACCESS_MODE],
                    "storageClassName": env("SANDBOX_STORAGE_CLASS", "local-path"),
                    "resources": {
                        "requests": {"storage": env("SANDBOX_WORKSPACE_SIZE", "2Gi")}
                    },
                },
            }],
            "service": False,
        },
    }
    _api().create_namespaced_custom_object(GROUP, VERSION, NS, PLURAL, body)
    log.info("created Sandbox %s for %s", name, task.get("repo_full"))
    return name


def delete_sandbox(name: str) -> None:
    try:
        _api().delete_namespaced_custom_object(GROUP, VERSION, NS, PLURAL, name)
        log.info("deleted Sandbox %s", name)
    except Exception as e:  # noqa: BLE001
        log.warning("delete Sandbox %s failed: %s", name, e)
