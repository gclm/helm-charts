#!/usr/bin/env python3
"""
1Panel appstore -> Helm chart converter.

Pure function: (upstream tree, overlay) -> generated/<app>/ charts.
Idempotent: same upstream SHA + overlay + converter version => identical output.

Design (inherited from docs/design-phase4-1panel-helm-plan.md §3, adapted):
- one chart per app, LATEST version only (chart version = normalized upstream ver)
- single generic template set (deployment/service/pvc/configmap/secret) per chart;
  all differences live in values.yaml
- blockers (docker.sock / cap_add / devices / network_mode:host / privileged /
  build / pid:host / untagged image) => skip + report, never emit a broken chart
- Database category excluded (DB reliability lives in handwritten charts/)
- overlay/apps/<app>/values-patch.yaml deep-merged into generated values
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

import yaml

HANDWRITTEN = {"postgresql", "mysql", "redis", "mongodb"}  # name clash with charts/
EXCLUDED_CATEGORIES = {"database", "数据库"}
DEFAULT_SIZE = "10Gi"

# ---------------------------------------------------------------- upstream scan

def load_yaml(path: Path):
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def normalize_ver(v: str):
    """'v1.2' / '5.7' / '6.1.2-standalone' -> '1.2.0' / '5.7.0' / '6.1.2+standalone'.
    'latest' dir maps to 0.0.0-latest so the untagged-image blocker catches it."""
    s = str(v).strip().lstrip("vV")
    if s.lower() == "latest":
        return "0.0.0-latest"
    m = re.fullmatch(r"(\d+(?:\.\d+)*)(?:-([A-Za-z0-9.-]+))?", s)
    if not m:
        return None
    parts = m.group(1).split(".")
    while len(parts) < 3:
        parts.append("0")
    out = ".".join(parts[:3])
    if m.group(2):
        out += "+" + m.group(2)
    return out


def ver_key(v: str):
    base = v.split("+")[0].split("-")[0]
    return tuple(int(x) for x in base.split("."))


def scan_apps(src: Path):
    """yield (app_name, app_meta, latest_ver_dir, latest_ver)."""
    apps_root = src / "apps"
    for app_dir in sorted(apps_root.iterdir() if apps_root.is_dir() else []):
        if not app_dir.is_dir():
            continue
        meta = load_yaml(app_dir / "data.yml")
        versions = []
        for vd in app_dir.iterdir():
            if vd.is_dir() and (vd / "docker-compose.yml").exists():
                nv = normalize_ver(vd.name)
                if nv:
                    versions.append((nv, vd))
        if not versions:
            # variant-style dirs (nvidia-0.20.0-cu130 / master / ...) — needs human placement via overlay
            yield app_dir.name, meta, None, None, "no semver version dir (variant naming, place via overlay)"
            continue
        versions.sort(key=lambda t: ver_key(t[0]))
        nv, vd = versions[-1]
        yield app_dir.name, meta, vd, nv, None


# ---------------------------------------------------------------- blockers

def image_untagged(image: str):
    if not image or ":" not in image:
        return True
    tag = image.rsplit(":", 1)[1]
    return tag in ("", "latest") or "/" in tag  # e.g. host:port/foo without tag


def detect_blockers(compose: dict):
    reasons = []
    for svc_name, svc in (compose.get("services") or {}).items():
        if not isinstance(svc, dict):
            continue
        image = svc.get("image") or ""
        if not image and "build" in svc:
            reasons.append(f"{svc_name}: local build")
        if image_untagged(image):
            reasons.append(f"{svc_name}: image not pinned to a tag ({image or 'no image'})")
        if svc.get("privileged"):
            reasons.append(f"{svc_name}: privileged")
        if svc.get("network_mode") == "host":
            reasons.append(f"{svc_name}: network_mode host")
        if svc.get("pid") == "host":
            reasons.append(f"{svc_name}: pid host")
        if svc.get("cap_add"):
            reasons.append(f"{svc_name}: cap_add {svc['cap_add']}")
        if svc.get("devices"):
            reasons.append(f"{svc_name}: devices")
        for v in svc.get("volumes") or []:
            src = v.split(":")[0] if isinstance(v, str) else (v.get("source") or "")
            if "docker.sock" in str(src):
                reasons.append(f"{svc_name}: docker socket mount")
    return reasons


# ---------------------------------------------------------------- conversion

def app_tags(meta):
    """upstream keeps category in tags (app-level, zh) and additionalProperties.tags (en)."""
    tags = set()
    for t in meta.get("tags") or []:
        tags.add(str(t).strip().lower())
    ap = meta.get("additionalProperties") or {}
    for t in ap.get("tags") or []:
        tags.add(str(t).strip().lower())
    return tags


def sanitize_name(s: str) -> str:
    """k8s-safe name part: lower, _->-, prefix if not starting with a letter."""
    out = str(s).lower().replace("_", "-")
    if not re.match(r"[a-z]", out):
        out = "app-" + out
    return out[:40]


def parse_volume(vol):
    if isinstance(vol, str):
        if ":" in vol:
            src, dst = vol.split(":", 1)[0], vol.split(":", 1)[1]
        else:
            src, dst = vol, vol
    else:
        src = str(vol.get("source") or vol.get("bind") or "")
        dst = str(vol.get("target") or vol.get("bind") or "")
    return src, dst.split(":")[0] if ":" in dst else dst


def split_image(image: str):
    """'registry/repo:tag' -> (registry, repository, tag)."""
    img = image.strip()
    tag = None
    if ":" in img and not img.rsplit(":", 1)[1].isdigit():
        img, tag = img.rsplit(":", 1)
    if "/" in img and "." in img.split("/")[0]:
        registry, repo = img.split("/", 1)
    else:
        registry, repo = "", img
    return registry, repo, tag


def convert_env_value(raw, form_fields, env_out, secret_out):
    """compose env value -> env entry dict for values.

    '${VAR}' references resolved against formFields:
      password+random -> valueFromSecret (generated Secret)
      others          -> valueFromEnv (values.env[VAR], set at install)
      unknown VAR     -> literal kept (e.g. ${CONTAINER_NAME} already substituted)
    """
    if raw is None:
        return None
    s = str(raw)
    m = re.fullmatch(r"\$\{([A-Za-z0-9_]+)\}", s)
    if m:
        var = m.group(1)
        f = form_fields.get(var)
        if f and f.get("type") == "password" and f.get("random"):
            secret_out[var] = True
            return {"name": None, "valueFromSecret": var}
        if f is not None:
            default = f.get("default")
            env_out[var] = "" if default is None else default
            return {"name": None, "valueFromEnv": var}
        return None  # variable not exposed via form fields -> drop (e.g. CONTAINER_NAME)
    m = re.search(r"\$\{([A-Za-z0-9_]+)\}", s)
    if m:  # embedded reference inside a longer string -> drop entry, report upstream shape
        return None
    return {"name": None, "value": s}


def probe_from_healthcheck(hc: dict):
    if not hc or not hc.get("test"):
        return None
    test = hc["test"]
    if isinstance(test, list):
        cmd = test if test and test[0] != "CMD-SHELL" else test[1:]
        cmd = " ".join(str(x) for x in cmd)
    else:
        cmd = str(test)
    return {
        "exec": cmd,
        "intervalSeconds": int(hc.get("interval", "10s").rstrip("smh") or 10),
        "timeoutSeconds": int(hc.get("timeout", "3s").rstrip("smh") or 3),
        "retries": int(hc.get("retries", 3) or 3),
    }


def convert_app(app_name, ver_dir: Path, ver_norm, form_fields, meta):
    compose = load_yaml(ver_dir / "docker-compose.yml")
    services_out = {}
    persistence_out = {}
    configmaps_out = {}
    env_out = {}
    secret_out = {}

    conf_files = {}
    conf_dir = ver_dir / "conf"
    if conf_dir.is_dir():
        for cf in sorted(conf_dir.rglob("*")):
            if cf.is_file() and cf.stat().st_size < 900_000:
                try:
                    conf_files[str(cf.relative_to(conf_dir))] = cf.read_text()
                except UnicodeDecodeError:
                    pass

    for svc_name, svc in (compose.get("services") or {}).items():
        if not isinstance(svc, dict) or not svc.get("image"):
            continue
        registry, repo, tag = split_image(svc["image"])
        env_list = []
        env_keys = set()
        raw_env = svc.get("environment") or {}
        if isinstance(raw_env, list):  # compose list form: ["KEY=VALUE", ...]
            env_pairs = {}
            for item in raw_env:
                if isinstance(item, str) and "=" in item:
                    k, v = item.split("=", 1)
                    env_pairs[k] = v
                elif isinstance(item, str):
                    env_pairs[item] = None
        else:
            env_pairs = raw_env
        for k, v in env_pairs.items():
            entry = convert_env_value(v, form_fields, env_out, secret_out)
            if entry:
                entry["name"] = k
                env_list.append(entry)
                env_keys.add(k)

        # command/entrypoint 里引用的 ${VAR}（formField）也要注入 env，否则容器 shell 拿不到
        cmd_blob = " ".join(
            str(x) for x in ([svc.get("command")] if isinstance(svc.get("command"), str) else (svc.get("command") or []))
            + ([svc.get("entrypoint")] if isinstance(svc.get("entrypoint"), str) else (svc.get("entrypoint") or []))
        )
        for m in re.finditer(r"\$\{([A-Za-z0-9_]+)[:}]", cmd_blob):
            var = m.group(1)
            if var in form_fields and var not in env_keys:
                entry = convert_env_value("${" + var + "}", form_fields, env_out, secret_out)
                if entry:
                    entry["name"] = var
                    env_list.append(entry)
                    env_keys.add(var)

        mounts = []
        for vol in svc.get("volumes") or []:
            src, dst = parse_volume(vol)
            if not dst:
                continue
            if src.startswith("./conf") or src.startswith("conf/") or src.startswith("/opt/1panel/apps/conf"):
                # conf 文件（单文件或目录）→ ConfigMap，subPath 逐文件挂载
                rel = src[2:] if src.startswith("./") else src
                rel_key = rel.split("/", 1)[1] if "/" in rel else rel
                if rel_key in conf_files:
                    cm_key = "conf"
                    if cm_key not in configmaps_out:
                        configmaps_out[sanitize_name(cm_key)] = {"data": conf_files, "mounts": []}
                    configmaps_out[sanitize_name(cm_key)]["mounts"].append(
                        {"mountPath": dst, "subPath": rel_key})
                continue
            if src.startswith("./") or src.startswith("/opt/1panel"):
                rel = src.lstrip("./")
                vol_key = "vol-" + (rel.replace("/", "-").replace(".", "-") or "data")
                persistence_out[sanitize_name(vol_key)] = {"size": DEFAULT_SIZE, "mountPath": dst}
                mounts.append({"name": sanitize_name(vol_key), "mountPath": dst})

        ports = svc.get("ports") or []
        port = None
        for p in ports:
            p_str = str(p)
            m = re.search(r":(\d+)", p_str) or re.fullmatch(r"(\d+)", p_str)
            if m:
                port = int(m.group(1))
                break
        hc = svc.get("healthcheck")
        svc_out = {
            "image": {"registry": registry, "repository": repo, "tag": tag},
            "env": env_list,
            "volumeMounts": mounts + [
                {"name": cm_key, "mountPath": m["mountPath"], "subPath": m["subPath"]}
                for cm_key, cm in configmaps_out.items() for m in cm.get("mounts", [])
            ],
        }
        if port:
            svc_out["port"] = port
        if svc.get("command"):
            cmd = svc["command"]
            svc_out["command"] = cmd if isinstance(cmd, list) else [cmd]
        probe = probe_from_healthcheck(hc)
        if probe:
            svc_out["probe"] = probe
        if svc.get("mem_limit"):
            svc_out["memoryLimit"] = str(svc["mem_limit"])
        services_out[sanitize_name(svc_name)] = svc_out

    values = {
        "services": services_out,
        "persistence": persistence_out,
        "configMaps": configmaps_out,
        "secrets": {k: {"generate": True} for k in secret_out},
        "env": env_out,
    }
    return values


# ---------------------------------------------------------------- chart emit

TEMPLATE_DEPLOYMENT = '''{{- range $name, $svc := .Values.services }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ $name }}
  labels: &labels
    app.kubernetes.io/name: {{ $name }}
    app.kubernetes.io/instance: {{ $.Release.Name }}
spec:
  replicas: 1
  {{- if $.Values.persistence }}
  strategy: {type: Recreate}
  {{- end }}
  selector:
    matchLabels: *labels
  template:
    metadata:
      labels: *labels
    spec:
      containers:
        - name: {{ $name }}
          image: "{{ $svc.image.registry }}/{{ $svc.image.repository }}:{{ $svc.image.tag }}"
          {{- with $svc.command }}
          command:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          {{- with $svc.env }}
          env:
            {{- range . }}
            - name: {{ .name }}
            {{- if hasKey . "valueFromSecret" }}
              valueFrom: {secretKeyRef: {name: {{ printf "%s-%s" $.Release.Name .valueFromSecret | lower | replace "_" "-" | trunc 63 | trimSuffix "-" }}, key: {{ .valueFromSecret }}}}
            {{- else if hasKey . "valueFromEnv" }}
              value: {{ index $.Values.env .valueFromEnv | quote }}
            {{- else }}
              value: {{ .value | quote }}
            {{- end }}
            {{- end }}
          {{- end }}
          {{- if $svc.port }}
          ports:
            - {name: http, containerPort: {{ $svc.port }}}
          {{- end }}
          {{- with $svc.probe }}
          readinessProbe:
            exec: {command: ["/bin/sh", "-c", {{ .exec | quote }}]}
            periodSeconds: {{ .intervalSeconds }}
            timeoutSeconds: {{ .timeoutSeconds }}
            failureThreshold: {{ .retries }}
          livenessProbe:
            exec: {command: ["/bin/sh", "-c", {{ .exec | quote }}]}
            periodSeconds: {{ .intervalSeconds }}
            timeoutSeconds: {{ .timeoutSeconds }}
            failureThreshold: {{ .retries }}
          {{- end }}
          {{- with $svc.volumeMounts }}
          volumeMounts:
            {{- range . }}
            - name: {{ .name }}
              mountPath: {{ .mountPath }}
              {{- if .subPath }}
              subPath: {{ .subPath }}
              {{- end }}
            {{- end }}
          {{- end }}
          {{- with $svc.memoryLimit }}
          resources:
            limits: {memory: {{ . | quote }}}
          {{- end }}
      volumes:
        {{- range $name, $p := $.Values.persistence }}
        - name: {{ $name }}
          persistentVolumeClaim: {claimName: {{ printf "%s-%s" $.Release.Name $name | lower | replace "_" "-" | trunc 63 | trimSuffix "-" }}}
        {{- end }}
        {{- range $name, $cm := $.Values.configMaps }}
        - name: {{ $name }}
          configMap: {name: {{ printf "%s-%s" $.Release.Name $name | lower | replace "_" "-" | trunc 63 | trimSuffix "-" }}}
        {{- end }}
---
{{- end }}
'''

TEMPLATE_PVC = '''{{- range $name, $p := .Values.persistence }}
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ printf "%s-%s" $.Release.Name $name | lower | replace "_" "-" | trunc 63 | trimSuffix "-" }}
spec:
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: {{ $p.size }}
---
{{- end }}
'''

TEMPLATE_SERVICE = '''{{- range $name, $svc := .Values.services }}
{{- if $svc.port }}
apiVersion: v1
kind: Service
metadata:
  name: {{ $name }}
  labels:
    app.kubernetes.io/name: {{ $name }}
    app.kubernetes.io/instance: {{ $.Release.Name }}
spec:
  selector:
    app.kubernetes.io/name: {{ $name }}
    app.kubernetes.io/instance: {{ $.Release.Name }}
  ports:
    - {name: http, port: {{ $svc.port }}, targetPort: http}
---
{{- end }}
{{- end }}
'''

TEMPLATE_SECRET = '''{{- range $name, $s := .Values.secrets }}
apiVersion: v1
kind: Secret
metadata:
  name: {{ printf "%s-%s" $.Release.Name $name | lower | replace "_" "-" | trunc 63 | trimSuffix "-" }}
type: Opaque
stringData:
  {{ $name }}: {{ randAlphaNum 32 | quote }}
{{- end }}
'''

TEMPLATE_CONFIGMAP = '''{{- range $name, $cm := .Values.configMaps }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ printf "%s-%s" $.Release.Name $name | lower | replace "_" "-" | trunc 63 | trimSuffix "-" }}
data:
  {{- range $f, $content := $cm.data }}
  {{ $f }}: |
{{ $content | indent 4 }}
  {{- end }}
---
{{- end }}
'''

NOTES = '''{{ .Chart.Name }} {{ .Chart.AppVersion }} converted from 1Panel appstore
(provenance: {{ .Chart.Annotations.source }}, upstream {{ .Chart.Annotations."upstream/sha" | trunc 8 }}).

{{- if .Values.secrets }}

Generated credentials (auto, stable across upgrades):
{{- range $k, $v := .Values.secrets }}
  kubectl get secret {{ printf "%s-%s" $.Release.Name $k | lower | replace "_" "-" | trunc 63 | trimSuffix "-" }} -o jsonpath='{.data.{{ $k }}}' | base64 -d
{{- end }}
{{- end }}
{{- if .Values.env }}

Install-time parameters (set with --set env.<KEY>=...):
{{- range $k, $v := .Values.env }}
  {{ $k }}{{ if $v }} = {{ $v }}{{ end }}
{{- end }}
{{- end }}
'''

CHART_ICON_NOTE = "converted from 1Panel-dev/appstore"


def deep_merge(base, override):
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for k, v in override.items():
            out[k] = deep_merge(out.get(k), v) if k in out else v
        return out
    return override


def write_chart(out_root: Path, app_name, ver_norm, meta, values, upstream_sha, license_text):
    cdir = out_root / app_name
    tdir = cdir / "templates"
    tdir.mkdir(parents=True, exist_ok=True)

    chart = {
        "apiVersion": "v2",
        "name": app_name,
        "description": (meta.get("name") or app_name) + " (converted from 1Panel appstore)",
        "type": "application",
        "version": ver_norm,
        "appVersion": ver_norm,
        "annotations": {
            "license": "GPL-3.0 (inherited from 1Panel-dev/appstore)",
            "source": "https://github.com/1Panel-dev/appstore",
            "upstream/sha": upstream_sha,
        },
    }
    (cdir / "Chart.yaml").write_text(yaml.safe_dump(chart, sort_keys=False, allow_unicode=True))

    (cdir / "values.yaml").write_text(
        yaml.safe_dump(values, sort_keys=True, allow_unicode=True, default_flow_style=False))

    (tdir / "deployment.yaml").write_text(TEMPLATE_DEPLOYMENT)
    (tdir / "pvc.yaml").write_text(TEMPLATE_PVC)
    (tdir / "service.yaml").write_text(TEMPLATE_SERVICE)
    (tdir / "secret.yaml").write_text(TEMPLATE_SECRET)
    (tdir / "configmap.yaml").write_text(TEMPLATE_CONFIGMAP)
    (cdir / "NOTES.txt").write_text(NOTES)
    if license_text:
        (cdir / "LICENSE").write_text(license_text)

    readme = [
        f"# {meta.get('name') or app_name}",
        "",
        meta.get("description") or meta.get("overview") or "",
        "",
        f"- 上游: 1Panel-dev/appstore `apps/{app_name}` @ `{upstream_sha[:12]}`",
        f"- 分类: {meta.get('category', 'unknown')}",
        "- 转换产物：不手改（见仓库 README 治理规则）；定制走 `overlay/apps/{app}/`",
        "",
        "## 安装",
        "",
        "```bash",
        f"helm install {app_name} gclm/{app_name}",
        "```",
    ]
    (cdir / "README.md").write_text("\n".join(readme) + "\n")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="upstream appstore checkout")
    ap.add_argument("--out", default="generated", help="output root")
    ap.add_argument("--sha", default="unknown", help="upstream commit SHA")
    args = ap.parse_args()

    src = Path(args.src)
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    # wipe previous output except governance files
    keep = {"README.md", "LICENSE", "CONVERSION-REPORT.md", "build-manifest.json"}
    for p in out_root.iterdir():
        if p.name not in keep and p.is_dir():
            shutil.rmtree(p)

    overlay_root = Path("overlay/apps")
    license_text = ""
    lic = src / "LICENSE"
    if lic.exists():
        license_text = lic.read_text()

    report = {"success": [], "skipped": [], "failed": []}
    manifest = {"upstream_sha": args.sha, "apps": {}}

    for app_name, meta, ver_dir, ver_norm, err in scan_apps(src):
        if err:
            report["skipped"].append(f"{app_name}: {err}")
            continue
        category_tags = app_tags(meta)
        if category_tags & EXCLUDED_CATEGORIES or app_name in HANDWRITTEN:
            report["skipped"].append(f"{app_name}: Database category excluded (use handwritten charts/)")
            continue
        compose = load_yaml(ver_dir / "docker-compose.yml")
        blockers = detect_blockers(compose)
        if blockers:
            report["skipped"].append(f"{app_name}: BLOCKED ({'; '.join(blockers)})")
            continue
        try:
            fields = {}
            vdata = load_yaml(ver_dir / "data.yml")
            for f in (vdata.get("additionalProperties") or {}).get("formFields") or []:
                if f.get("envKey"):
                    fields[f["envKey"]] = f
            values = convert_app(app_name, ver_dir, ver_norm, fields, meta)
            patch = overlay_root / app_name / "values-patch.yaml"
            if patch.exists():
                values = deep_merge(values, load_yaml(patch))
            if not values.get("services"):
                report["failed"].append(f"{app_name}: no convertible service")
                continue
            write_chart(out_root, app_name, ver_norm, meta, values, args.sha, license_text)
            content_sha = hashlib.sha256(
                (out_root / app_name / "values.yaml").read_bytes()).hexdigest()[:12]
            report["success"].append(f"{app_name} ({ver_norm}) sha:{content_sha}")
            manifest["apps"][app_name] = {"version": ver_norm, "sha": content_sha, "status": "success"}
        except Exception as e:  # noqa: BLE001 - converter must not die on one app
            report["failed"].append(f"{app_name}: {type(e).__name__}: {e}")

    # report
    lines = [
        "# Conversion report",
        "",
        f"- upstream: 1Panel-dev/appstore @ `{args.sha}`",
        f"- success: **{len(report['success'])}** · skipped: **{len(report['skipped'])}** · failed: **{len(report['failed'])}**",
        "",
        "## Success",
        "", *[f"- {x}" for x in report["success"]], "",
        "## Skipped", "", *[f"- {x}" for x in report["skipped"]], "",
        "## Failed", "", *[f"- {x}" for x in report["failed"] or ["(none)"]], "",
    ]
    (out_root / "CONVERSION-REPORT.md").write_text("\n".join(lines))
    (out_root / "build-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))

    print(f"success={len(report['success'])} skipped={len(report['skipped'])} failed={len(report['failed'])}")
    if report["failed"]:
        print("FAILED:", *report["failed"][:20], sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
