"""Create/delete Sandbox CRs (agents.x-k8s.io/v1alpha1) for each fix task.

v0.4.6 schema: spec.podTemplate (full PodSpec) + spec.volumeClaimTemplates + spec.service.
No lifecycle/expiry field -> we cap with activeDeadlineSeconds and self-delete on completion.
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
IMAGE = env("SANDBOX_IMAGE", "agent-runner:v0.1.4")


def _api() -> client.CustomObjectsApi:
    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()
    return client.CustomObjectsApi()


def _pod_template(task: dict, task_b64: str) -> dict:
    return {
        "metadata": {"labels": {"app": "agent-runner"}},
        "spec": {
            "restartPolicy": "Never",
            "serviceAccountName": "agent-runner",
            "activeDeadlineSeconds": int(env("SANDBOX_DEADLINE_SECONDS", "1200")),
            "securityContext": {"runAsNonRoot": True, "runAsUser": 1000, "fsGroup": 1000},
            "containers": [{
                "name": "agent",
                "image": IMAGE,
                "imagePullPolicy": "Never",
                "command": ["python", "-m", "app.agent"],
                "workingDir": "/workspace",
                "envFrom": [
                    {"secretRef": {"name": "agent-runner-secret"}},
                    {"configMapRef": {"name": "agent-runner-config"}},
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
                    "requests": {"cpu": "200m", "memory": "512Mi"},
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
            "labels": {"app": "agent-runner"},
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
                    "accessModes": ["ReadWriteOnce"],
                    "storageClassName": env("SANDBOX_STORAGE_CLASS", "local-path"),
                    "resources": {"requests": {"storage": env("SANDBOX_WORKSPACE_SIZE", "2Gi")}},
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
